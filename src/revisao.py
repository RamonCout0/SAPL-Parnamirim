"""Revisao manual: o que o OCR nao entregou com seguranca sai como imagem.

O documento e oficial, entao nao existe "chute aceitavel". Toda indicacao que
nao passar nos criterios de confianca vai para output/revisao_manual/:

  - a pagina renderizada em PNG, legivel, para conferir com o olho
  - uma linha no glossario.csv com o que a maquina conseguiu ler e as colunas
    em branco para voce escrever a versao correta - E' O ARQUIVO QUE VOCE
    EDITA, mas abra num programa de planilha (Excel/LibreOffice): um CSV
    de texto corrido, num editor de codigo, fica uma linha so gigante
  - REVISAO.md, so para LEITURA: o mesmo conteudo do glossario, mas um bloco
    por indicacao com as imagens incorporadas - abra o preview de Markdown do
    editor para ver tudo formatado e com a pagina ao lado do texto

Depois de preencher o glossario, rode o pipeline de novo: os valores manuais
tem prioridade sobre qualquer coisa que a maquina tenha deduzido.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pypdfium2 as pdfium

# Colunas que VOCE preenche. O resto e informativo.
#
# CONFIRMAR existe para os motivos que NAO tem nada para digitar: "numero
# deduzido pela sequencia" ou "bloco com 1 pagina" nao sao erro de ementa nem
# de autor - sao avisos estruturais. Preencher EMENTA_MANUAL/AUTOR_ID_MANUAL
# nesses casos nao adianta nada, porque o motivo que esta bloqueando e outro.
# Escreva "sim" em CONFIRMAR para dizer "eu vi a pagina, esta tudo certo assim
# mesmo".
COLUNAS_MANUAIS = ["EMENTA_MANUAL", "AUTOR_ID_MANUAL", "CONFIRMAR"]

# Ordem pensada para quem abre o CSV bruto (nao no Excel): as colunas que voce
# de fato edita ficam logo no comeco da linha, antes dos textos longos
# (ementa lida, sugestao do modelo) que empurrariam tudo para fora da tela.
CABECALHO_GLOSSARIO = [
    "numero",
    "ano",
    "paginas",
    "EMENTA_MANUAL",
    "AUTOR_ID_MANUAL",
    "CONFIRMAR",
    "motivo",
    "autor_lido_pela_maquina",
    "sugestao_ollama_autor",
    "ementa_lida_pela_maquina",
    "sugestao_ollama_ementa",
    "imagens",
]


def exportar_paginas_png(
    caminho_pdf: str,
    paginas: list[int],
    destino: Path,
    prefixo: str,
    escala: float = 2.2,
) -> list[str]:
    """Renderiza paginas do PDF em PNG. escala 2.2 ~ 158 dpi, boa para ler."""
    destino.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(caminho_pdf)
    gerados = []
    try:
        for n in paginas:
            pagina = doc[n - 1]
            imagem = pagina.render(scale=escala).to_pil()
            arquivo = destino / f"{prefixo}_pg{n:03d}.png"
            imagem.save(arquivo)
            gerados.append(arquivo.name)
    finally:
        doc.close()
    return gerados


def escrever_glossario(linhas: list[dict], caminho: Path) -> None:
    """CSV com BOM para o Excel abrir com os acentos certos."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=CABECALHO_GLOSSARIO, delimiter=";")
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({k: linha.get(k, "") for k in CABECALHO_GLOSSARIO})


def escrever_revisao_md(linhas: list[dict], caminho: Path) -> None:
    """Mesmo conteudo do glossario, mas formatado para LER - abra o preview
    de Markdown do editor. A edicao continua sendo feita no glossario.csv;
    isto aqui e so para nao precisar decifrar CSV bruto para saber o que
    cada indicacao precisa.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    blocos = [
        "# Indicações para revisão manual",
        "",
        f"{len(linhas)} indicação(ões). A edição é feita em `glossario.csv` "
        "(abra num programa de planilha) - preencha `EMENTA_MANUAL` e/ou "
        "`AUTOR_ID_MANUAL` lá. Isto aqui é só para consulta.",
        "",
        "---",
    ]
    for l in linhas:
        blocos += [
            "",
            f"## {l['numero']}/{l['ano']} — página(s) {l['paginas']}",
            "",
            f"**Motivo da revisão:** {l['motivo']}",
            "",
            f"**Autor lido pela máquina:** {l['autor_lido_pela_maquina']}",
        ]
        if l.get("sugestao_ollama_autor"):
            blocos.append(f"**Sugestão do modelo:** {l['sugestao_ollama_autor']}")
        blocos += [
            "",
            "**Ementa lida pela máquina:**",
            "",
            f"> {l['ementa_lida_pela_maquina'] or '_(vazia)_'}",
        ]
        if l.get("sugestao_ollama_ementa"):
            blocos += ["", f"**Trecho sugerido pelo modelo:** {l['sugestao_ollama_ementa']}"]
        blocos += ["", "**Página(s) escaneada(s):**", ""]
        for img in (l.get("imagens") or "").split(","):
            img = img.strip()
            if img:
                blocos.append(f"![{img}](imagens/{img})")
        blocos += ["", "---"]

    caminho.write_text("\n".join(blocos) + "\n", encoding="utf-8")


def ler_glossario(caminho: Path) -> dict[str, dict]:
    """Le o glossario preenchido. Chave: "numero/ano". Ignora linhas em branco."""
    if not caminho.exists():
        return {}
    preenchidos: dict[str, dict] = {}
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            numero = (linha.get("numero") or "").strip()
            ano = (linha.get("ano") or "").strip()
            if not numero or not ano:
                continue
            ementa = (linha.get("EMENTA_MANUAL") or "").strip()
            autor = (linha.get("AUTOR_ID_MANUAL") or "").strip()
            confirmar = (linha.get("CONFIRMAR") or "").strip()
            if not ementa and not autor and not confirmar:
                continue
            item: dict = {}
            if ementa:
                item["ementa"] = ementa
            if autor:
                try:
                    item["autor_id"] = int(autor)
                except ValueError:
                    item["autor_id_invalido"] = autor
            if confirmar:
                item["confirmado"] = True
            preenchidos[f"{numero}/{ano}"] = item
    return preenchidos


def escrever_referencia_autores(ids: dict, caminho: Path) -> None:
    """Tabela de IDs para consultar enquanto preenche o glossario."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    parlamentares = [a for a in ids["autores"] if a.get("parlamentar")]
    linhas = [
        "# IDs de autor para o glossario",
        "",
        "Use a coluna ID na coluna `AUTOR_ID_MANUAL` do glossario.csv.",
        "Tipo de autor no SAPL e sempre **Parlamentar (2)**.",
        "",
        "| ID | Nome no SAPL |",
        "|---:|--------------|",
    ]
    linhas += [
        f"| {a['id']} | {a['nome']} |"
        for a in sorted(parlamentares, key=lambda x: x["nome"])
    ]
    linhas += [
        "",
        "## Órgãos e comissões (não usar com tipo Parlamentar)",
        "",
        "| ID | Nome no SAPL |",
        "|---:|--------------|",
    ]
    linhas += [
        f"| {a['id']} | {a['nome']} |"
        for a in sorted(
            (a for a in ids["autores"] if not a.get("parlamentar")),
            key=lambda x: x["nome"],
        )
    ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
