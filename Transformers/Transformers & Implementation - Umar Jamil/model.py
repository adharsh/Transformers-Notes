import torch
import torch.nn as nn
import math

class InputEmbeddings(nn.Module):

    def __init__(self, d_model: int, vocab_size: int) -> None:
        # d_model: The size of the embedding vector
        # vocab_size: Number of tokens in the vocabulary

        super().__init__()
        self.d_model = d_model
        self.vocab_size = vocab_size
        
        # Stores the embeddings of the tokens
        self.embedding = nn.Embedding(num_embeddings=vocab_size, embedding_dim=d_model)

    def forward(self, x):
        # Could just do self.embedding(x)
        # But in the paper, we multiply those weights by sqrt(d_model)

        # (batch, seq_len) --> (batch, seq_len, d_model)
        return self.embedding(x) * math.sqrt(self.d_model)

class PositionalEncoding(nn.Module):
        # Since num samples of nn.Linear'out = nn.Linear's in
    def __init__(self, d_model: int, seq_len: int, dropout: float) -> None:
        # d_model: size of the embedding vector
        # seq_len: max length of the sequence defined by number of tokens
        # dropout: dropout rate

        super().__init__()
        self.d_model = d_model
        self.seq_len = seq_len
        self.dropout = nn.Dropout(dropout)

        # Positional Encoding formulas:
        # $P(k, 2i) = \sin(k \cdot \exp(2i \cdot \frac{- \log 10000}{d_{model}}))$  
        # $P(k, 2i+1) = \cos(k \cdot \exp(2i \cdot \frac{- \log 10000}{d_{model}}))$  

        # Create a matrix of shape (seq_len, d_model)
        pe = torch.zeros(seq_len, d_model)

        # Create a position vector of shape (seq_len)
        position = torch.arange(0, seq_len, dtype=torch.float).unsqueeze(1) # (seq_len, 1)
        # Create a 2i vector of shape (d_model)
        two_i = torch.arange(0, d_model, 2).float()

        # Create a vector of shape (d_model)
        div_term = torch.exp(two_i * (-math.log(10000.0) / d_model)) # (d_model / 2)

        # Apply to all positions, but only skip dims in embedding space by 2
        ## Apply sine to even indices - 0::2 is the same as 0:seq_len:2: 0, 2, 4, etc.
        pe[:, 0::2] = torch.sin(position * div_term)
        ## Apply cosine to odd indices - 1::2 is the same as 1:seq_len:2: 1, 3, 5, etc
        pe[:, 1::2] = torch.cos(position * div_term)

        # Add a batch dimension to the positional encoding
        #  so now we can handle batches of sequences
        pe = pe.unsqueeze(0) # (1, seq_len, d_model)

        # Register the positional encoding as a non-trainable buffer 
        #  that is read-only during backprop/training
        self.register_buffer('pe', pe)

    def forward(self, x):
        # x: (batch_size, seq_len, d_model)
        # pe: (batch_size, seq_len, d_model)

        # Retrieve the first x.shape[1] positional encodings and apply to all embeddings in all batches
        #  ex: x: (32, 50, 512), pe: (1, 100, 512), only first 50 embeddings are updated
        #  pe is broadcasted to all batches
        x = x + (self.pe[:, :x.shape[1], :]).requires_grad_(False) # (batch, seq_len, d_model)
        # We expliclty add requires_grad_(False) even tho it may not be necessary
        #  since we don't want to backprop through the positional encoding

        return self.dropout(x)

class FeedForwardBlock(nn.Module):
    # FFN(x) = \max(0, xW_1^T + b_1)W_2^T + b_2
    # x: (batch, seq_len, d_model)
    # W_1: (d_ff, d_model)
    # b_1: (d_ff)
    # W_2: (d_model, d_ff)
    # b_2: (d_model)

    # We project the input x to a higher dimensional space d_ff
    #  facts are learned in this higher dimensional space
    # Then apply a ReLU activation
    # Then project back to the original dimension d_model
     
    def __init__(self, d_model: int, d_ff: int, dropout: float) -> None:
        super().__init__()
        self.linear_1 = nn.Linear(d_model, d_ff) # w1 and b1
        self.dropout = nn.Dropout(dropout)
        self.linear_2 = nn.Linear(d_ff, d_model) # w2 and b2

    def forward(self, x):
        # Note: input_dim of linear_1 = output_dim of linear_2
        # (batch, seq_len, d_model) --> (batch, seq_len, d_ff) --> (batch, seq_len, d_model)
        return self.linear_2(self.dropout(torch.relu(self.linear_1(x))))
    
class MultiHeadAttentionBlock(nn.Module):
    # d_k: dim of query, key, and value vectors for each head

    def __init__(self, d_model: int, h: int, dropout: float) -> None:
        # d_model: size of embedding
        # h: number of heads
        # dropout: dropout rate

        super().__init__()
        self.d_model = d_model
        self.h = h

        # Make sure d_model is divisible by h
        # Each head consists of d_model/h dimensions
        assert d_model % h == 0, "d_model is not divisible by h"

        # Size of projected down dimension for key, query, and value vectors
        #  128 dim space
        self.d_k = d_model // h

        # Wq: (d_model, d_model)
        # Wk: (d_model, d_model)
        # Wv: (d_model, d_model)
        self.w_q = nn.Linear(d_model, d_model, bias=False)
        self.w_k = nn.Linear(d_model, d_model, bias=False)
        self.w_v = nn.Linear(d_model, d_model, bias=False)

        # Wo: (d_model, d_model)
        self.w_o = nn.Linear(d_model, d_model, bias=False)

        self.dropout = nn.Dropout(dropout)

    @staticmethod
    def attention(query, key, value, mask, dropout: nn.Dropout):
        # Roughly: 1. Computes query-key dot product 2. Applies softmax (per query) 3. Dot product with value

        d_k = query.shape[-1]

        # query: (batch, h, seq_len, d_k)
        # key: (batch, h, seq_len, d_k)
        # key.transpose(-2, -1): (batch, h, d_k, seq_len)
        # query @ key.transpose(-2, -1): (batch, h, seq_len, d_k) @ (batch, h, d_k, seq_len) = (batch, h, seq_len, seq_len)
        attention_scores = (query @ key.transpose(-2, -1)) / math.sqrt(d_k)

        # Since Q*K^T, for a single q_i, all k_j are considered
        # so operations like masking or softmax are applied row-wise for each row across columns
        #  across column => dim=-1

        if mask is not None:
            # Write a very low value (indicating -inf) to the positions where mask == 0
            attention_scores.masked_fill_(mask == 0, -1e9)

        # Apply softmax on last dim
        # (batch, h, seq_len, seq_len)
        attention_scores = attention_scores.softmax(dim=-1) 

        if dropout is not None:
            attention_scores = dropout(attention_scores)

        # Notice how the attention scores are used to weight the value vectors
        #  since dim(attention_scores @ value) = dim(value)
        # (batch, h, seq_len, seq_len) * (batch, h, seq_len, d_k) = (batch, h, seq_len, d_k), (batch, h, seq_len, seq_len)
        return (attention_scores @ value), attention_scores
        # return attention scores which can be used for visualization

    def forward(self, q, k, v, mask):
        # Multihead query, key, value generation
        # query = (batch, seq_len, d_model) * (d_model, d_model) = (batch, seq_len, d_model)
        # key =   (batch, seq_len, d_model) * (d_model, d_model) = (batch, seq_len, d_model)
        # value = (batch, seq_len, d_model) * (d_model, d_model) = (batch, seq_len, d_model)
        # Multihead query, key, value generation, but split into h
        # query = (batch, seq_len, d_model) * (d_model, h*d_k) = (batch, seq_len, h*d_k)}
        # key =   (batch, seq_len, d_model) * (d_model, h*d_k) = (batch, seq_len, h*d_k)
        # value = (batch, seq_len, d_model) * (d_model, h*d_k) = (batch, seq_len, h*d_k)
        query = self.w_q(q) 
        key = self.w_k(k)
        value = self.w_v(v)

        # query = (batch, seq_len, d_model) -> (batch, seq_len, h, d_k) -> (batch, h, seq_len, d_k)
        # key   = (batch, seq_len, d_model) -> (batch, seq_len, h, d_k) -> (batch, h, seq_len, d_k)
        # value = (batch, seq_len, d_model) -> (batch, seq_len, h, d_k) -> (batch, h, seq_len, d_k)
        query = query.view(query.shape[0], query.shape[1], self.h, self.d_k).transpose(1, 2)
        key = key.view(key.shape[0], key.shape[1], self.h, self.d_k).transpose(1, 2)
        value = value.view(value.shape[0], value.shape[1], self.h, self.d_k).transpose(1, 2)

        # Calculate attention
        # (batch, h, seq_len, d_k), (batch, h, seq_len, seq_len)
        x, self.attention_scores = MultiHeadAttentionBlock.attention(query, key, value, mask, self.dropout)
         
        # Concat all the heads together
        # (batch, h, seq_len, d_k) -> (batch, seq_len, h, d_k) -> (batch, seq_len, d_model)
        x = x.transpose(1, 2).contiguous().view(x.shape[0], -1, self.h * self.d_k)

        # Multiply by Wo
        # (batch, seq_len, d_model) * (d_model, d_model) = (batch, seq_len, d_model)
        return self.w_o(x)

class LayerNormalization(nn.Module):
    # Normalize each sample in a batch independently
    #  rather than normalizing across each dim/feature in a sample
    #  $\alpha (x - \mu)/(\sigma + \epsilon) + \beta
    #  alpha and beta are learned to shift and scale the normalized x
    #  adding epsilon adds numerical stability to prevent division by zero
    def __init__(self, input_dim: int, eps:float=10**-6) -> None:
        super().__init__()
        self.eps = eps
        self.alpha = nn.Parameter(torch.ones(input_dim)) # alpha is a learnable parameter
        self.bias = nn.Parameter(torch.zeros(input_dim)) # bias is a learnable parameter

    def forward(self, x):
        # x: (batch, seq_len, input_dim)

        # Mean across last dimension: (batch, seq_len, 1)
        # Keep the dimension for broadcasting (we don't want: (batch, seq_len))
        mean = x.mean(dim = -1, keepdim = True) 

        # Across last dimension: (batch, seq_len, 1)
        # Keep the dimension for broadcasting (we don't want: (batch, seq_len))
        std = x.std(dim = -1, keepdim = True) 

        # eps is to prevent dividing by zero or when std is very small
        return self.alpha * (x - mean) / (std + self.eps) + self.bias

class ResidualConnection(nn.Module):
    
        def __init__(self, features: int, dropout: float) -> None:
            super().__init__()
            self.dropout = nn.Dropout(dropout)
            self.norm = LayerNormalization(features)
    
        def forward(self, x, sublayer):
            # sublayer is previous layer
            # In the paper:
            # return x + self.dropout(self.norm(sublayer(x)))
            return x + self.dropout(sublayer(self.norm(x)))

class EncoderBlock(nn.Module):

    def __init__(self, features: int, self_attention_block: MultiHeadAttentionBlock, feed_forward_block: FeedForwardBlock, dropout: float) -> None:
        super().__init__()
        self.self_attention_block = self_attention_block
        self.feed_forward_block = feed_forward_block
        self.residual_connections = nn.ModuleList([ResidualConnection(features, dropout) for _ in range(2)])

    def forward(self, x, src_mask):
        # Sequence is interacting with itself self.self_attention_block(x, x, x, src_mask) hence why it's called self attention
        x = self.residual_connections[0](x, lambda x: self.self_attention_block(x, x, x, src_mask))
        x = self.residual_connections[1](x, self.feed_forward_block)
        return x
    
class Encoder(nn.Module):

    def __init__(self, features: int, layers: nn.ModuleList) -> None:
        super().__init__()
        self.layers = layers
        self.norm = LayerNormalization(features)

    def forward(self, x, mask):
        for layer in self.layers:
            x = layer(x, mask)
        return self.norm(x)

class DecoderBlock(nn.Module):

    def __init__(self, features: int, self_attention_block: MultiHeadAttentionBlock, cross_attention_block: MultiHeadAttentionBlock, feed_forward_block: FeedForwardBlock, dropout: float) -> None:
        super().__init__()
        self.self_attention_block = self_attention_block
        self.cross_attention_block = cross_attention_block
        self.feed_forward_block = feed_forward_block
        self.residual_connections = nn.ModuleList([ResidualConnection(features, dropout) for _ in range(3)])

    def forward(self, x, encoder_output, src_mask, tgt_mask):
        # Multihead attention params: query(x), key(encoder_output), value(encoder_output)
        #  query comes from decoder
        # src_mask: encoder mask, tgt_mask = decoder mask 
        # src: src english, tgt: target language - italian
        x = self.residual_connections[0](x, lambda x: self.self_attention_block(x, x, x, tgt_mask))
        x = self.residual_connections[1](x, lambda x: self.cross_attention_block(x, encoder_output, encoder_output, src_mask))
        x = self.residual_connections[2](x, self.feed_forward_block)
        return x
    
class Decoder(nn.Module):

    def __init__(self, features: int, layers: nn.ModuleList) -> None:
        super().__init__()
        self.layers = layers
        self.norm = LayerNormalization(features)

    def forward(self, x, encoder_output, src_mask, tgt_mask):
        for layer in self.layers:
            x = layer(x, encoder_output, src_mask, tgt_mask)
        return self.norm(x)

class ProjectionLayer(nn.Module):
    # Linear layer that's projecting the embedding into the vocabulary

    def __init__(self, d_model, vocab_size) -> None:
        super().__init__()
        self.proj = nn.Linear(d_model, vocab_size)

    def forward(self, x) -> None:
        # (batch, seq_len, d_model) * (d_model, vocab_size) = (batch, seq_len, vocab_size)
        # Then compute log softmax on last dim vocab_size
        return torch.log_softmax(self.proj(x), dim=-1)
    
class Transformer(nn.Module):
    # Why not use forward method? We can reuse

    def __init__(self, encoder: Encoder, decoder: Decoder, src_embed: InputEmbeddings, tgt_embed: InputEmbeddings, src_pos: PositionalEncoding, tgt_pos: PositionalEncoding, projection_layer: ProjectionLayer) -> None:
        super().__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.src_embed = src_embed
        self.tgt_embed = tgt_embed
        self.src_pos = src_pos
        self.tgt_pos = tgt_pos
        self.projection_layer = projection_layer

    def encode(self, src, src_mask):
        # (batch, seq_len, d_model)
        src = self.src_embed(src)
        src = self.src_pos(src)
        return self.encoder(src, src_mask)
    
    def decode(self, encoder_output: torch.Tensor, src_mask: torch.Tensor, tgt: torch.Tensor, tgt_mask: torch.Tensor):
        # (batch, seq_len, d_model)
        tgt = self.tgt_embed(tgt)
        tgt = self.tgt_pos(tgt)
        return self.decoder(tgt, encoder_output, src_mask, tgt_mask)
    
    def project(self, x):
        # (batch, seq_len, vocab_size)
        return self.projection_layer(x)
    
def build_transformer(src_vocab_size: int, tgt_vocab_size: int, src_seq_len: int, tgt_seq_len: int, d_model: int=512, N: int=6, h: int=8, dropout: float=0.1, d_ff: int=2048) -> Transformer:
    # N - number of layers, for encoding and decoding
    # h - number of heads
    # d_ff - number of neurons in the hidden layer of the feed forward network
    # Create the embedding layers
    src_embed = InputEmbeddings(d_model, src_vocab_size)
    tgt_embed = InputEmbeddings(d_model, tgt_vocab_size)

    # Create the positional encoding layers
    src_pos = PositionalEncoding(d_model, src_seq_len, dropout)
    tgt_pos = PositionalEncoding(d_model, tgt_seq_len, dropout)
    
    # Create the encoder blocks
    encoder_blocks = []
    for _ in range(N):
        encoder_self_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        feed_forward_block = FeedForwardBlock(d_model, d_ff, dropout)
        encoder_block = EncoderBlock(d_model, encoder_self_attention_block, feed_forward_block, dropout)
        encoder_blocks.append(encoder_block)

    # Create the decoder blocks
    decoder_blocks = []
    for _ in range(N):
        decoder_self_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        decoder_cross_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        feed_forward_block = FeedForwardBlock(d_model, d_ff, dropout)
        decoder_block = DecoderBlock(d_model, decoder_self_attention_block, decoder_cross_attention_block, feed_forward_block, dropout)
        decoder_blocks.append(decoder_block)
    
    # Create the encoder and decoder
    encoder = Encoder(d_model, nn.ModuleList(encoder_blocks))
    decoder = Decoder(d_model, nn.ModuleList(decoder_blocks))
    
    # Create the projection layer
    projection_layer = ProjectionLayer(d_model, tgt_vocab_size)
    
    # Create the transformer
    transformer = Transformer(encoder, decoder, src_embed, tgt_embed, src_pos, tgt_pos, projection_layer)
    
    # Initialize the parameters
    for p in transformer.parameters():
        if p.dim() > 1:
            nn.init.xavier_uniform_(p)
    
    return transformer

def get_model(config, vocab_src_len, vocab_tgt_len):
    model = build_transformer(vocab_src_len, vocab_tgt_len, config["seq_len"], config['seq_len'], d_model=config['d_model'])
    return model
