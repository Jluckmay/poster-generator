# Exemplos / Examples

Este diretório contém exemplos de dados estruturados para geração de pôsteres.

## Arquivos
- `sample_poster.json`: Dados completos de um pôster acadêmico de demonstração pronto para envio à API.

## Testando via cURL
Com o servidor rodando (`python server.py`):

```bash
# Gerar PDF direto a partir do JSON
curl -X POST http://127.0.0.1:5000/api/generate \
  -F "data=<examples/sample_poster.json" \
  --output poster.pdf

# Gerar pacote .ZIP com LaTeX + imagens
curl -X POST "http://127.0.0.1:5000/api/generate?format=zip" \
  -F "data=<examples/sample_poster.json" \
  --output poster.zip
```

