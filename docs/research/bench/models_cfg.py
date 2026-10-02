# key -> (gguf, pooling, doc_prefix_native, query_prefix_native, notes)
NOMAD_DOC = "search_document: "; NOMAD_Q = "search_query: "
MODELS = {
 "nomic15":  dict(gguf="nomic-embed-text-v1.5.Q8_0.gguf", pooling="mean", doc=NOMAD_DOC, q=NOMAD_Q, dim=768),
 "nomic2moe":dict(gguf="nomic-embed-text-v2-moe.Q8_0.gguf", pooling="mean", doc=NOMAD_DOC, q=NOMAD_Q, dim=768),
 "gemma300": dict(gguf="embeddinggemma-300M-Q8_0.gguf", pooling="mean", doc="title: none | text: ", q="task: search result | query: ", dim=768),
 "qwen3_06": dict(gguf="Qwen3-Embedding-0.6B-Q8_0.gguf", pooling="last", doc="", q="Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ", dim=1024),
 "bgem3":    dict(gguf="bge-m3-q8_0.gguf", pooling="cls", doc="", q="", dim=1024),
 "arcticm2": dict(gguf="arctic-embed-m-v2-q8_0.gguf", pooling="cls", doc="", q="query: ", dim=768),
 "arcticl2": dict(gguf="arctic-embed-l-v2-q8_0.gguf", pooling="cls", doc="", q="query: ", dim=1024),
 "jina5nano": dict(gguf="v5-nano-retrieval-Q8_0.gguf", pooling="last", doc="Document: ", q="Query: ", dim=768),
 "granite_r2": dict(gguf="granite-embedding-english-r2.Q8_0.gguf", pooling="cls", doc="", q="", dim=768),
}
SERVER_ARGS = "-ngl 999 -c 4096 -b 4096 -ub 4096"
