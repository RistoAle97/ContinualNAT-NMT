import torch
import math
from torch import nn
from .TransformerCore import TransformerCore
from ..inference import greedy_decoding, beam_decoding


class Transformer(TransformerCore):

    def __init__(self,
                 src_vocab_size: int,
                 tgt_vocab_size: int = None,
                 d_model: int = 512,
                 n_heads: int = 8,
                 num_encoder_layers: int = 6,
                 num_decoder_layers: int = 6,
                 dim_ff: int = 2048,
                 dropout: float = 0.1,
                 layer_norm_eps: float = 1e-6,
                 norm_first: bool = False,
                 share_embeddings_src_tgt: bool = True,
                 share_embeddings_tgt_out: bool = True) -> None:
        """
        Transformer model whose architecture is based on the paper "Attention is all you need" from Vaswani et al.
        https://arxiv.org/pdf/1706.03762.pdf. The model, differently from the pytorch implementation, comes with
        embeddings, positional encoding, linear output and softmax layers. The model expects inputs with the format
        (batch_size, seq_len).
        :param src_vocab_size: input language vocabulary size.
        :param tgt_vocab_size: target language vocabulary size, if no value is passed, then it will have the same size
            of the source one.
        :param d_model: embedding dimension (default=512).
        :param n_heads: the number of heads in the multi-attention mechanism (default=8).
        :param num_encoder_layers: the number of encoder layers (default=6).
        :param num_decoder_layers: the number of decoder layers (default=6).
        :param dim_ff: dimension of the feedforward sublayer (default=2048).
        :param dropout: the dropout value (default=0.1).
        :param layer_norm_eps: the eps value in the layer normalization (default=1e-6).
        :param norm_first: if True, encoder and decoder layers will perform LayerNorms before other attention and
            feedforward operations, otherwise after. Default: False (after).
        :param share_embeddings_src_tgt: whether to share the weights beetween source and target embedding layers
            (default=True).
        :param share_embeddings_tgt_out: whether to share the weights beetween the target embeddings and the linear
            output (default=True).
        """
        super().__init__(src_vocab_size, tgt_vocab_size, d_model, n_heads, num_encoder_layers, num_decoder_layers,
                         dim_ff, dropout, layer_norm_eps, norm_first, share_embeddings_src_tgt,
                         share_embeddings_tgt_out)
        # Initialize weights
        self._init_weights()
        self.src_embedding.weight.data.normal_(0, self.d_model ** (-0.5))
        if not self.share_embeddings_src_trg:
            self.tgt_embedding.weight.data.normal_(0, self.d_model ** (-0.5))

    def _init_weights(self):
        for p in self.parameters():
            if p.dim() > 1 and not isinstance(p, nn.Embedding):
                nn.init.xavier_uniform_(p)

    def forward(self,
                src_input: torch.Tensor,
                tgt_input: torch.Tensor,
                d_mask: torch.Tensor = None,
                e_pad_mask: torch.Tensor = None,
                d_pad_mask: torch.Tensor = None) -> torch.Tensor:
        """
        Process masked source and target sequences.
        """
        # Embeddings and positional encoding
        e_input = self.src_embedding(src_input)  # (batch_size, seq_len, d_model)
        e_input = self.positional_encoder(e_input * math.sqrt(self.d_model))
        d_input = self.tgt_embedding(tgt_input)  # (batch_size, seq_len, d_model)
        d_input = self.positional_encoder(d_input * math.sqrt(self.d_model))

        # Encoder and decoder
        e_output = self.encoder(e_input, None, e_pad_mask)
        d_output = self.decoder(d_input, e_output, d_mask, None, d_pad_mask, e_pad_mask)

        # Linear output
        output = self.linear_output(d_output)  # (batch_size, seq_len, tgt_vocab_size)
        return output

    def generate(self,
                 input_ids: torch.Tensor,
                 e_pad_mask: torch.Tensor,
                 sos_token_id: int,
                 eos_token_id: int,
                 pad_token_id: int,
                 max_new_tokens: int = 10,
                 beam_size: int = 4) -> torch.Tensor:
        if beam_size == 1:
            output = greedy_decoding(self, input_ids, sos_token_id, eos_token_id, pad_token_id, max_new_tokens)
        else:
            output = beam_decoding(self, input_ids, sos_token_id, eos_token_id, beam_size=beam_size)

        return output
