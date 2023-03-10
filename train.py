import torch
import yaml
from transformers import MBartTokenizer
from datasets import load_dataset
from torch import nn
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from torch.optim import Adam
from torch.optim.lr_scheduler import LambdaLR
from tqdm import tqdm
from src.data import TranslationDataset, BatchCollator
from src.models import Transformer
from src import model_size, model_n_parameters, generate_causal_mask, shift_tokens_right, compute_lr
from typing import Dict


if __name__ == "__main__":
    # Set-up device
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Training on: {device}")

    # Retrieve configurations
    with open("config.yaml") as config_file:
        config = yaml.load(config_file, Loader=yaml.FullLoader)

    huggingface_dataset = config["train_dataset"]
    langs: Dict[str, str] = config["languages"]
    batch_size = config["batch_size"]
    max_length = config["max_length"]
    padding = config["padding"]
    warmup_steps = config["warmup_steps"]
    verbose = config["verbose_training"]
    log_steps = config["log_steps"]
    shift_labels_right = config["shift_labels_right"]

    # Define source and target language
    src_lang = "en"
    tgt_lang = "de"

    # Tokenizer
    tokenizer: MBartTokenizer = MBartTokenizer.from_pretrained("tokenizers/mbart_tokenizer_cmlm",
                                                               src_lang=langs[src_lang], tgt_lang=langs[tgt_lang])
    print(f"Retrieved {tokenizer.__class__.__name__} with vocab size: {len(tokenizer)}\n")

    # Dataset
    dataset = load_dataset("yhavinga/ccmatrix", f"{src_lang}-{tgt_lang}",
                           cache_dir=f"D:/MasterDegreeThesis/datasets/ccmatrix_{src_lang}_{tgt_lang}",
                           split="train[:4096]", verification_mode="no_checks")

    dataset_train = TranslationDataset(src_lang, tgt_lang, dataset)
    batch_collator = BatchCollator(tokenizer, max_length=max_length, padding=padding)
    dataloader_train = DataLoader(dataset_train, batch_size, collate_fn=batch_collator, drop_last=True)

    # Model
    transformer = Transformer(len(tokenizer), norm_first=True).to(device)
    n_parameters, n_trainable_parameters = model_n_parameters(transformer)
    transformer_size = model_size(transformer)
    print(f"\nUsing {transformer.__class__.__name__} model:")
    print(f"\tParameters: {n_parameters}\n"
          f"\tTrainable parameters: {n_trainable_parameters}\n"
          f"\tSize: {transformer_size}\n")

    # Useful token ids
    pad_token = tokenizer.pad_token_id
    src_lang_token = tokenizer.lang_code_to_id[langs[src_lang]]
    tgt_lang_token = tokenizer.lang_code_to_id[langs[tgt_lang]]
    sos_token = tokenizer.bos_token_id
    eos_token = tokenizer.eos_token_id

    # Define loss function, optimizer and scheduler
    loss_fn = nn.CrossEntropyLoss(ignore_index=pad_token, label_smoothing=0.1)
    optimizer = Adam(transformer.parameters(), lr=5e-5, betas=(0.9, 0.997), eps=1e-9)
    # scheduler = LambdaLR(optimizer, lambda steps: compute_lr(steps, transformer.d_model, 4000))

    # Train loop
    current_step = 0
    epochs = 10
    dataloader_tqdm = tqdm(dataloader_train)
    transformer.train()
    board = SummaryWriter()
    for epoch in range(epochs):
        total_loss = 0
        for step, batch in enumerate(dataloader_tqdm):
            # Retrieve encoder inputs and labels, then create decoder inputs
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            if shift_labels_right:
                decoder_input_ids = shift_tokens_right(labels, pad_token, tgt_lang_token).to(device)
            else:
                decoder_input_ids = labels[:, :-1].to(device)
                labels = labels[:, 1:]

            # Create masks
            e_pad_mask = (input_ids == pad_token).to(device)
            d_pad_mask = (decoder_input_ids == pad_token).to(device)
            d_mask = generate_causal_mask(decoder_input_ids.shape[-1]).to(device)

            # Compute predictions and loss
            logits = transformer(input_ids, decoder_input_ids, d_mask, e_pad_mask, d_pad_mask)
            loss = loss_fn(logits.contiguous().view(-1, logits.size(-1)), labels.contiguous().view(-1))

            # Update weights and do one step for both optmizer and scheduler
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            # scheduler.step()

            total_loss += loss.item()
            if current_step % log_steps == 0:
                dataloader_tqdm.set_postfix(loss=str(loss.item)[0:6])

            current_step += 1
            board.add_scalar("Loss/train", loss, current_step)
            board.add_scalar("Learning rate", optimizer.param_groups[0]["lr"], current_step)

        print(f"Epoch {epoch} ended at step {current_step}, Loss: {total_loss / len(list(dataloader_train))}\n")

    board.flush()
    board.close()
