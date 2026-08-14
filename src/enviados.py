"""Registro do que ja foi SALVO no SAPL - a trava contra cadastro em dobro.

Existe por causa do envio automatico. Enquanto o programa so preenchia a tela,
"ja fiz essa?" era pergunta para os olhos de quem estava salvando; agora quem
aperta o botao e o programa, e uma indicacao cadastrada duas vezes vira dois
registros oficiais da mesma indicacao - defeito no acervo, nao bug de tela.

Por que nao serve o output/pdfs_gerados.json nem o "apagar o PDF depois de
anexar": os dois falam de arquivo gerado, nao de cadastro feito. Depois do
envio automatico o PDF continua na pasta (foi o programa que anexou, ninguem
apagou nada), entao nenhum dos dois distingue "enviada" de "ainda nao".

Fica em output/ do lado do pdfs_gerados.json, e como ele e versionado
(excecao no .gitignore): e o unico lugar que sabe o que ja virou registro
publico. Se este arquivo se perder, o programa deixa de conhecer o que ja foi
enviado - por isso ele nunca e reescrito do zero, so acrescido.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import OUTPUT_DIR

ENVIADOS = OUTPUT_DIR / "enviados.json"

_DOC = (
    "Indicacoes ja cadastradas no SAPL pelo envio automatico, por 'numero/ano'. "
    "O programa se recusa a enviar de novo o que estiver aqui. Nao apague: sem "
    "este arquivo nao ha como saber o que ja virou registro oficial."
)


def ler_enviados(caminho: Path | None = None) -> dict[str, dict]:
    """O que ja foi cadastrado. Vazio se o arquivo ainda nao existe.

    Arquivo corrompido levanta erro em vez de devolver vazio, de proposito:
    um dicionario vazio aqui significaria "nada foi enviado ainda" e liberaria
    o reenvio de tudo. Melhor a tela reclamar do que cadastrar em dobro.
    """
    caminho = caminho or ENVIADOS
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{caminho} esta corrompido ({e}). E o registro do que ja foi "
            "cadastrado no SAPL - conserte o JSON a mao em vez de apagar, "
            "senao o programa perde a conta e cadastra tudo de novo."
        ) from e
    enviados = dados.get("enviados")
    if not isinstance(enviados, dict):
        raise ValueError(
            f"{caminho} nao tem a chave 'enviados' com o formato esperado. "
            "Conserte o arquivo a mao - ele e a trava contra cadastro em dobro."
        )
    return enviados


def registrar_envio(
    identificador: str,
    *,
    url: str = "",
    caminho: Path | None = None,
) -> dict:
    """Grava que ESTA indicacao virou registro no SAPL. Devolve o registro.

    Reler antes de gravar (em vez de manter tudo em memoria) e o que garante
    que nada se perde se o programa fechar no meio de uma sessao longa.
    """
    caminho = caminho or ENVIADOS
    enviados = ler_enviados(caminho)
    # Nao sobrescreve um registro anterior: a PRIMEIRA vez e a que virou o
    # cadastro de verdade; um segundo carimbo por cima so apagaria a pista.
    registro = enviados.setdefault(identificador, {
        "em": datetime.now().isoformat(timespec="seconds"),
        "url": url,
    })
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps({"_doc": _DOC, "enviados": enviados},
                   ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    return registro
