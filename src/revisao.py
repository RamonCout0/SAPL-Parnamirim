"""Revisao manual: o que o OCR nao entregou com seguranca sai como imagem.

O documento e oficial, entao nao existe "chute aceitavel". Toda indicacao que
nao passar nos criterios de confianca vai para output/revisao_manual/:

  - a pagina renderizada em PNG, legivel, para conferir com o olho
  - uma linha no glossario.csv com o que a maquina conseguiu ler e as colunas
    em branco para voce escrever a versao correta

Depois de preencher, rode o pipeline de novo: os valores manuais tem
prioridade sobre qualquer coisa que a maquina tenha deduzido.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pypdfium2 as pdfium

# Colunas que VOCE preenche. O resto e informativo.
COLUNAS_MANUAIS = ["EMENTA_MANUAL", "AUTOR_ID_MANUAL"]

CABECALHO_GLOSSARIO = [
    "numero",
    "ano",
    "paginas",
    "imagens",
    "motivo",
    "ementa_lida_pela_maquina",
    "sugestao_ollama_ementa",
    "EMENTA_MANUAL",
    "autor_lido_pela_maquina",
    "sugestao_ollama_autor",
    "AUTOR_ID_MANUAL",
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
            if not ementa and not autor:
                continue
            item: dict = {}
            if ementa:
                item["ementa"] = ementa
            if autor:
                try:
                    item["autor_id"] = int(autor)
                except ValueError:
                    item["autor_id_invalido"] = autor
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
