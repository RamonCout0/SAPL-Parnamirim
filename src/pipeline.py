"""Orquestracao: tudo que estiver em input/ -> 1 PDF e 1 registro por indicacao.

Fluxo:
    input/*.pdf -> texto OCR -> blocos -> campos (regex) -> Ollama -> criterio
                                                                          |
                                                    +---------------------+---------------+
                                                    |                                      |
                                              PRONTO p/ SAPL                      REVISAO MANUAL
                                         (indicacoes.json/csv)             (PNG da pagina + glossario)

A cada execucao, output/pdfs/ e output/markdown/ sao APAGADOS e reconstruidos
do zero a partir do que estiver em input/ NAQUELE MOMENTO - se voce tirar um
PDF de input/, a proxima rodada simplesmente nao inclui mais as indicacoes
dele. O glossario.csv (correcoes manuais) e config/aliases_aprendidos.json
NAO sao apagados: sao trabalho seu, sobrevivem entre execucoes.

Os valores que voce escrever no glossario.csv vencem qualquer deducao da
maquina na proxima execucao.
"""
from __future__ import annotations

import csv
import json
import shutil
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from . import ollama_client
from .autores import ResolvedorAutor
from .campos import extrair_ementa, extrair_nome_autor
from .config import (
    INPUT_DIR,
    MARKDOWN_DIR,
    OUTPUT_DIR,
    PDFS_DIR,
    carregar_ids,
    garantir_dirs,
)
from .detect import auditar, classificar_paginas, inferir_numeros, montar_blocos
from .progresso import Progresso
from .revisao import (
    escrever_glossario,
    escrever_referencia_autores,
    escrever_revisao_md,
    exportar_paginas_png,
    ler_glossario,
)
from .textlayer import extrair_paginas

# Criterios para uma indicacao entrar sozinha no SAPL.
EMENTA_MIN = 40
EMENTA_MAX = 900
CONFIANCA_MIN = 0.6

REVISAO_DIR = OUTPUT_DIR / "revisao_manual"
GLOSSARIO = REVISAO_DIR / "glossario.csv"

# Um nome de arquivo terminando em "@AAAA.pdf" (o padrao que voce ja usa,
# tipo "..._300_A_201@2023.pdf") define o ano so daquele arquivo, sem precisar
# passar --ano toda vez. Sem isso no nome, vale o --ano do comando (ou 2023).
_ANO_NO_NOME_RE = re.compile(r"@(\d{4})(?:\.pdf)?$", re.IGNORECASE)


@dataclass
class Indicacao:
    numero: int
    ano: int
    pagina_inicial: int
    pagina_final: int
    qtd_paginas: int
    arquivo_origem: str = ""   # o PDF grande, em input/, de onde ela veio
    arquivo_pdf: str = ""      # o PDF fatiado, em output/pdfs/
    usou_ocr: bool = False     # alguma pagina nao tinha OCR embutido -
                                # o texto dela veio do Tesseract (informativo;
                                # nao muda sozinho o criterio de aprovacao)

    # campos do formulario do SAPL
    tipo_materia_id: int = 6
    tipo_autor_id: int = 2
    regime_id: int = 1
    tipo_apresentacao: str = "E"     # sempre Escrita ("O" seria Oral)
    autor_id: int = 0
    autor_nome_sapl: str = ""
    ementa: str = ""

    # rastreabilidade
    autor_no_documento: str = ""
    apelido_no_documento: str = ""
    autor_origem: str = ""
    autor_escore: float = 0.0
    verbo: str = ""
    ementa_regex: str = ""
    ementa_metodo: str = ""
    confianca: float = 0.0
    numero_inferido: bool = False
    # Marcado quando voce escreve "sim" na coluna CONFIRMAR do glossario -
    # diz "eu vi a pagina, esta tudo certo assim mesmo". Existe porque
    # "numero deduzido" e "1 pagina" nao tem ementa/autor para corrigir: sem
    # isso, essas duas ficariam pedindo revisao para sempre, mesmo depois de
    # voce conferir a imagem.
    confirmado_manual: bool = False

    # Palpites do Ollama. NAO entram no formulario: existem so para aparecer no
    # glossario e acelerar a conferencia humana contra o PNG da pagina.
    sugestao_ementa_ollama: str = ""
    sugestao_autor_ollama: str = ""

    status: str = "revisao"          # "pronto" | "revisao"
    motivos: list[str] = field(default_factory=list)
    avisos_bloco: list[str] = field(default_factory=list)

    @property
    def identificador(self) -> str:
        return f"{self.numero}/{self.ano}"

    @property
    def nome_arquivo(self) -> str:
        return f"{self.numero}-{self.ano}.pdf"


def _texto_do_bloco(mapa: dict[int, str], ini: int, fim: int) -> str:
    return "\n".join(mapa.get(n, "") for n in range(ini, fim + 1))


def _ano_do_nome_arquivo(caminho: Path) -> int | None:
    m = _ANO_NO_NOME_RE.search(caminho.stem + ".pdf")
    return int(m.group(1)) if m else None


def processar_pasta(
    pasta_input: str | Path = INPUT_DIR,
    ano_padrao: int = 2023,
    usar_ollama: bool = True,
    gerar_pdfs: bool = True,
) -> list[Indicacao]:
    """Processa TODOS os PDFs de uma pasta e combina num unico resultado."""
    garantir_dirs()
    ids = carregar_ids()
    pasta_input = Path(pasta_input)

    # Aceita tanto uma pasta (o uso normal: processa tudo que tiver dentro)
    # quanto o caminho de um unico PDF (util para testar so um arquivo).
    if pasta_input.is_file():
        pdfs = [pasta_input]
    else:
        pdfs = sorted(pasta_input.glob("*.pdf"))

    if not pdfs:
        print(f"Nenhum PDF encontrado em {pasta_input}")
        print("Zerando o output (nao ha nada em input\\ agora) ...")
        # Nao para aqui: continua ate o fim com uma lista vazia, para o
        # output refletir de verdade "nada" em vez de deixar para tras os
        # PDFs fatiados e o glossario de uma rodada anterior.
    else:
        print(f"{len(pdfs)} arquivo(s) em {pasta_input}:")
        for p in pdfs:
            print(f"  {p.name}")

    if usar_ollama:
        if not ollama_client.esta_no_ar():
            print("AVISO: Ollama nao respondeu; seguindo apenas com regex.")
            usar_ollama = False
        else:
            print(f"Ollama ok, modelo {ollama_client.OLLAMA_MODEL}")

    resolvedor = ResolvedorAutor(ids, usar_ollama=usar_ollama)

    # As saidas DERIVADAS (pdfs fatiados, markdown por indicacao) sao
    # reconstruidas do zero a cada execucao - e o que garante que, se voce
    # tirar um PDF de input/, as indicacoes dele somem do output tambem em vez
    # de ficar "fantasma" de uma rodada anterior. glossario.csv e
    # aliases_aprendidos.json NAO entram aqui: sao preservados de proposito.
    for pasta in (PDFS_DIR, MARKDOWN_DIR):
        if pasta.exists():
            shutil.rmtree(pasta)
        pasta.mkdir(parents=True, exist_ok=True)

    todas: list[Indicacao] = []
    citacoes_todas: list[dict] = []
    origem_de: dict[tuple[int, int], str] = {}

    for caminho_pdf in pdfs:
        ano = _ano_do_nome_arquivo(caminho_pdf) or ano_padrao
        print(f"\n--- {caminho_pdf.name} (ano {ano}) ---")
        indicacoes, citacoes = _extrair_um_pdf(str(caminho_pdf), ano, usar_ollama, resolvedor)
        citacoes_todas.extend(citacoes)

        for ind in indicacoes:
            chave = (ind.numero, ind.ano)
            if chave in origem_de:
                # Em avisos_bloco isto seria so informativo. Vai em motivos de
                # proposito: e o que forca a indicacao para revisao em vez de
                # deixar dois arquivos disputarem silenciosamente o mesmo
                # numero (um deles venceria sem voce saber que houve colisao).
                ind.motivos.append(
                    f"numero {ind.identificador} tambem aparece em "
                    f"{origem_de[chave]} - dois arquivos descrevem a mesma indicacao?"
                )
            else:
                origem_de[chave] = caminho_pdf.name
        todas.extend(indicacoes)

    print(f"\n{len(todas)} indicacoes ao todo. Aplicando correcoes do glossario ...")
    _aplicar_correcoes_manuais(todas, ids, resolvedor)
    for ind in todas:
        _classificar(ind)

    resolvedor.salvar_cache()
    resolvedor.salvar_aprendidos()

    if gerar_pdfs:
        print("Gerando um PDF por indicacao ...")
        por_origem: dict[str, list[Indicacao]] = {}
        for ind in todas:
            por_origem.setdefault(ind.arquivo_origem, []).append(ind)
        for origem, inds in por_origem.items():
            _fatiar_pdf(origem, inds)

    print("Gravando resultados ...")
    _gravar_saidas(todas, citacoes_todas, ids)

    print("Preparando revisao manual ...")
    _preparar_revisao(todas, ids)

    return todas


def _extrair_um_pdf(
    caminho_pdf: str,
    ano: int,
    usar_ollama: bool,
    resolvedor: ResolvedorAutor,
) -> tuple[list[Indicacao], list[dict]]:
    """Extrai e classifica as indicacoes de UM pdf. Sem aplicar o glossario
    ainda - isso e feito uma vez so, depois de juntar todos os arquivos."""
    paginas = extrair_paginas(caminho_pdf, mostrar_progresso=True)
    mapa = {p.numero: p.texto for p in paginas}
    via_ocr = {p.numero for p in paginas if p.via_ocr}
    print(f"  {len(paginas)} paginas")

    inicios, citacoes = classificar_paginas(paginas)
    blocos = auditar(montar_blocos(inferir_numeros(inicios, ano), len(paginas), ano))
    print(f"  {len(blocos)} indicacoes")

    indicacoes: list[Indicacao] = []
    barra = Progresso(len(blocos), prefixo="  ementa/autor ")
    for i, b in enumerate(blocos, start=1):
        texto = _texto_do_bloco(mapa, b.pagina_inicial, b.pagina_final)
        ind = Indicacao(
            numero=b.numero,
            ano=b.ano,
            pagina_inicial=b.pagina_inicial,
            pagina_final=b.pagina_final,
            qtd_paginas=b.qtd_paginas,
            numero_inferido=b.numero_inferido,
            avisos_bloco=list(b.avisos),
            arquivo_origem=caminho_pdf,
            usou_ocr=any(n in via_ocr for n in range(b.pagina_inicial, b.pagina_final + 1)),
        )

        res_ementa = extrair_ementa(texto)
        ind.verbo = res_ementa["verbo"] or ""
        ind.ementa_regex = res_ementa["ementa"]
        ind.ementa_metodo = res_ementa["metodo"]
        ind.ementa = res_ementa["ementa"]
        ind.confianca = res_ementa["confianca"]

        # O Ollama entra SO quando o regex nao conseguiu, e so como sugestao.
        # A ementa que vai para o SAPL e sempre o texto literal do OCR ou o
        # que voce escreveu no glossario - nunca uma reescrita do modelo, que
        # nos testes chegou a trocar "Rosano Taveira da Cunha" por
        # "Rosano Taveiraara Cunha".
        if usar_ollama and not ind.ementa:
            try:
                achou = ollama_client.achar_ementa(texto)
                if achou["achou"]:
                    ind.sugestao_ementa_ollama = achou["ementa"]
                ind.motivos.append(
                    "ementa: verbo ilegivel no OCR - transcrever pelo PNG"
                )
            except ollama_client.OllamaIndisponivel as e:
                ind.motivos.append(f"ollama falhou: {e}")
        elif not ind.ementa:
            ind.motivos.append("ementa: verbo ilegivel no OCR - transcrever pelo PNG")

        nome = extrair_nome_autor(texto)
        ind.autor_no_documento = nome["nome"]
        ind.apelido_no_documento = nome["apelido"]
        achado = resolvedor.resolver(nome["nome"], nome["apelido"])
        ind.autor_id = achado["id"]
        ind.autor_nome_sapl = achado["nome"]
        ind.autor_origem = achado["origem"]
        ind.autor_escore = achado["escore"]
        if not ind.autor_id:
            ind.motivos.append(f"autor: {achado['motivo']}")
            if usar_ollama:
                ind.sugestao_autor_ollama = resolvedor.sugerir_com_ollama(
                    nome["nome"], nome["apelido"]
                )
        elif achado["certeza"] != "alta":
            ind.motivos.append(f"autor: certeza {achado['certeza']} ({achado['origem']})")

        indicacoes.append(ind)
        barra.avancar()

    return indicacoes, citacoes


def _aplicar_correcoes_manuais(
    todas: list[Indicacao], ids: dict, resolvedor: ResolvedorAutor
) -> None:
    manuais = ler_glossario(GLOSSARIO)
    if manuais:
        print(f"glossario preenchido: {len(manuais)} correcoes manuais")

    nomes = {a["id"]: a["nome"] for a in ids["autores"]}
    aprendidos: list[str] = []

    for ind in todas:
        manual = manuais.get(ind.identificador)
        if not manual:
            continue
        if manual.get("ementa"):
            ind.ementa = manual["ementa"]
            ind.ementa_metodo = "manual"
            ind.confianca = 1.0
            ind.motivos = [m for m in ind.motivos if not m.startswith("ementa:")]
        if manual.get("autor_id"):
            ind.autor_id = manual["autor_id"]
            ind.autor_nome_sapl = nomes.get(manual["autor_id"], "")
            ind.autor_origem = "manual"
            ind.motivos = [m for m in ind.motivos if not m.startswith("autor:")]
            # Vira alias permanente: as outras indicacoes com o mesmo nome
            # civil passam a resolver sozinhas na proxima rodada.
            if resolvedor.aprender(
                ind.autor_no_documento, manual["autor_id"], ind.identificador
            ):
                aprendidos.append(f"{ind.autor_no_documento} -> {ind.autor_nome_sapl}")
        if manual.get("autor_id_invalido"):
            ind.motivos.append(
                f"autor: AUTOR_ID_MANUAL '{manual['autor_id_invalido']}' nao e numero"
            )
        if manual.get("confirmado"):
            ind.confirmado_manual = True

    if aprendidos:
        print(f"aprendeu {len(aprendidos)} nome(s) civil(is) do glossario:")
        for a in aprendidos:
            print(f"  {a}")
        print("rode de novo para aplicar aos demais casos iguais")


def _classificar(ind: Indicacao) -> None:
    """Decide se a indicacao pode ir sozinha para o SAPL."""
    motivos = list(ind.motivos)

    if not ind.ementa:
        motivos.append("ementa vazia")
    elif len(ind.ementa) < EMENTA_MIN:
        motivos.append(f"ementa curta demais ({len(ind.ementa)} caracteres)")
    elif len(ind.ementa) > EMENTA_MAX:
        motivos.append(f"ementa longa demais ({len(ind.ementa)} caracteres)")

    if ind.confianca < CONFIANCA_MIN:
        motivos.append(f"confianca da ementa baixa ({ind.confianca})")
    if not ind.autor_id:
        if not any(m.startswith("autor:") for m in motivos):
            motivos.append("autor nao identificado")
    # Estes dois nao tem campo de ementa/autor para corrigir - so o CONFIRMAR
    # do glossario (ind.confirmado_manual) resolve.
    if ind.numero_inferido and not ind.confirmado_manual:
        motivos.append("numero deduzido pela sequencia - confirmar no papel")
    if ind.qtd_paginas == 1 and not ind.confirmado_manual:
        motivos.append("bloco com 1 pagina - verso ausente no scan")

    ind.motivos = motivos
    ind.status = "pronto" if not motivos else "revisao"


def _fatiar_pdf(caminho_pdf: str, indicacoes: list[Indicacao]) -> None:
    leitor = PdfReader(caminho_pdf)
    barra = Progresso(len(indicacoes), prefixo=f"  {Path(caminho_pdf).name[:30]:<30} ")
    for ind in indicacoes:
        escritor = PdfWriter()
        for n in range(ind.pagina_inicial, ind.pagina_final + 1):
            escritor.add_page(leitor.pages[n - 1])
        destino = PDFS_DIR / ind.nome_arquivo
        with open(destino, "wb") as f:
            escritor.write(f)
        ind.arquivo_pdf = str(destino)
        barra.avancar()


def _gravar_saidas(indicacoes: list[Indicacao], citacoes: list[dict], ids: dict) -> None:
    (OUTPUT_DIR / "indicacoes.json").write_text(
        json.dumps(
            {
                "total": len(indicacoes),
                "prontas": sum(1 for i in indicacoes if i.status == "pronto"),
                "revisao": sum(1 for i in indicacoes if i.status == "revisao"),
                "numeros_ignorados": citacoes,
                "indicacoes": [asdict(i) for i in indicacoes],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    colunas = [
        "status", "numero", "ano", "paginas", "arquivo_origem", "arquivo_pdf",
        "tipo_materia_id", "ano_sapl", "numero_sapl",
        "tipo_autor_id", "autor_id", "autor_nome_sapl", "regime_id",
        "tipo_apresentacao", "ementa", "autor_no_documento", "autor_origem",
        "autor_escore", "verbo", "ementa_metodo", "confianca", "usou_ocr", "motivos",
    ]
    with open(OUTPUT_DIR / "indicacoes.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(colunas)
        for i in indicacoes:
            w.writerow([
                i.status, i.numero, i.ano,
                f"{i.pagina_inicial}-{i.pagina_final}",
                Path(i.arquivo_origem).name if i.arquivo_origem else "",
                Path(i.arquivo_pdf).name if i.arquivo_pdf else "",
                i.tipo_materia_id, i.ano, i.numero,
                i.tipo_autor_id, i.autor_id, i.autor_nome_sapl, i.regime_id,
                i.tipo_apresentacao, i.ementa, i.autor_no_documento,
                i.autor_origem, i.autor_escore,
                i.verbo, i.ementa_metodo, i.confianca,
                "sim" if i.usou_ocr else "não", " | ".join(i.motivos),
            ])

    # Markdown por indicacao, para leitura humana rapida.
    for ind in indicacoes:
        (MARKDOWN_DIR / f"{ind.numero}-{ind.ano}.md").write_text(
            "\n".join([
                f"# Indicação nº {ind.identificador}",
                "",
                f"- **Status:** {ind.status}",
                f"- **Arquivo de origem:** {Path(ind.arquivo_origem).name}",
                f"- **Páginas no PDF original:** {ind.pagina_inicial}-{ind.pagina_final}",
                f"- **Autor no documento:** {ind.autor_no_documento or '—'}",
                f"- **Autor no SAPL:** {ind.autor_nome_sapl or '—'} (id {ind.autor_id})",
                f"- **Verbo:** {ind.verbo or '—'}",
                f"- **Confiança:** {ind.confianca}",
                f"- **Texto veio de OCR local (Tesseract):** {'sim' if ind.usou_ocr else 'não'}",
                "",
                "## Ementa",
                "",
                ind.ementa or "_não extraída_",
                "",
                "## Motivos de revisão" if ind.motivos else "",
                "",
                "\n".join(f"- {m}" for m in ind.motivos),
            ]),
            encoding="utf-8",
        )


def _preparar_revisao(indicacoes: list[Indicacao], ids: dict) -> None:
    pendentes = [i for i in indicacoes if i.status == "revisao"]
    escrever_referencia_autores(ids, REVISAO_DIR / "IDS_DE_AUTOR.md")

    # Apaga PNG de rodadas anteriores: se uma indicacao deixou de ser
    # pendente (ou o PDF dela sumiu de input/), a imagem dela nao pode
    # continuar na pasta pedindo revisao.
    pasta_img = REVISAO_DIR / "imagens"
    if pasta_img.exists():
        vivos = {f"{i.numero}-{i.ano}" for i in pendentes}
        for antigo in pasta_img.glob("*.png"):
            if antigo.name.rsplit("_pg", 1)[0] not in vivos:
                antigo.unlink()

    if not pendentes:
        # Regrava vazio em vez de so sair: se a rodada anterior deixou
        # pendencias e agora nao ha nenhuma (porque o PDF sumiu de input/ ou
        # tudo foi resolvido), o glossario.csv antigo nao pode continuar
        # apontando indicacoes que nao existem mais.
        if GLOSSARIO.exists():
            ja_preenchidos = ler_glossario(GLOSSARIO)
            if ja_preenchidos:
                reserva = GLOSSARIO.with_name("glossario_anterior.csv")
                GLOSSARIO.replace(reserva)
                print(f"glossario anterior preservado em {reserva.name}")
        escrever_glossario([], GLOSSARIO)
        escrever_revisao_md([], REVISAO_DIR / "REVISAO.md")
        print("nada pendente")
        return

    linhas = []
    barra = Progresso(len(pendentes), prefixo="  paginas (png) ")
    for ind in pendentes:
        imagens = exportar_paginas_png(
            ind.arquivo_origem,
            list(range(ind.pagina_inicial, ind.pagina_final + 1)),
            REVISAO_DIR / "imagens",
            prefixo=f"{ind.numero}-{ind.ano}",
        )
        barra.avancar()
        linhas.append({
            "numero": ind.numero,
            "ano": ind.ano,
            "paginas": f"{ind.pagina_inicial}-{ind.pagina_final}",
            "imagens": ", ".join(imagens),
            "motivo": " | ".join(ind.motivos),
            "ementa_lida_pela_maquina": ind.ementa,
            "sugestao_ollama_ementa": ind.sugestao_ementa_ollama,
            "EMENTA_MANUAL": "",
            "autor_lido_pela_maquina": (
                f"{ind.autor_no_documento or '(nada legivel)'}"
                f" -> {ind.autor_nome_sapl or '?'}"
            ),
            "sugestao_ollama_autor": ind.sugestao_autor_ollama,
            "AUTOR_ID_MANUAL": "",
            "CONFIRMAR": "",
        })

    # Nao sobrescreve um glossario que voce ja comecou a preencher.
    if GLOSSARIO.exists():
        ja_preenchidos = ler_glossario(GLOSSARIO)
        if ja_preenchidos:
            reserva = GLOSSARIO.with_name("glossario_anterior.csv")
            GLOSSARIO.replace(reserva)
            print(f"glossario anterior preservado em {reserva.name}")

    escrever_glossario(linhas, GLOSSARIO)
    escrever_revisao_md(linhas, REVISAO_DIR / "REVISAO.md")
    print(f"{len(pendentes)} indicacoes para revisar em {GLOSSARIO}")
    print(f"leitura formatada em {REVISAO_DIR / 'REVISAO.md'} (abra o preview de Markdown)")
