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
dele.

O que NUNCA e apagado e o que voce escreveu: config/correcoes.json (ementa,
autor e "ja conferi" de cada indicacao) e config/aliases_aprendidos.json
(nome civil -> nome politico). Esses dois vencem qualquer deducao da maquina
na rodada seguinte.

O output/revisao_manual/glossario.csv NAO e memoria: e uma janela para as
pendentes de agora, regravada a cada rodada ja preenchida com o que voce
digitou antes. Editar ele a mao continua funcionando - o conteudo e importado
para o correcoes.json no inicio da rodada seguinte, antes de qualquer
regravacao.
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
from .datas import achar_pagina_do_carimbo, data_de_apresentacao
from .config import (
    INPUT_DIR,
    MARKDOWN_DIR,
    OUTPUT_DIR,
    PDFS_DIR,
    carregar_ids,
    garantir_dirs,
)
from .detect import (
    auditar,
    classificar_paginas,
    inferir_numeros,
    marcar_suspeitos,
    montar_blocos,
)
from .progresso import Progresso
from .revisao import (
    CORRECOES,
    escrever_glossario,
    escrever_referencia_autores,
    escrever_revisao_md,
    exportar_paginas_png,
    importar_do_glossario,
    ler_correcoes,
)
from .textlayer import extrair_paginas

# Criterios para uma indicacao entrar sozinha no SAPL.
EMENTA_MIN = 40
EMENTA_MAX = 900
CONFIANCA_MIN = 0.6

REVISAO_DIR = OUTPUT_DIR / "revisao_manual"
GLOSSARIO = REVISAO_DIR / "glossario.csv"

# Registro de quais indicacoes ja tiveram o PDF fatiado gerado alguma vez.
# Existe porque "o arquivo nao existe" e ambiguo: pode ser que nunca foi
# gerado, ou pode ser que voce apagou de proposito depois de anexar no SAPL -
# so esse registro permite distinguir os dois casos e nao recriar o segundo.
PDFS_GERADOS = OUTPUT_DIR / "pdfs_gerados.json"

# Um nome de arquivo terminando em "@AAAA.pdf" (o padrao que voce ja usa,
# tipo "..._300_A_201@2023.pdf") define o ano so daquele arquivo, sem precisar
# passar --ano toda vez. Sem isso no nome, vale o --ano do comando (ou 2023).
_ANO_NO_NOME_RE = re.compile(r"@(\d{4})(?:\.pdf)?$", re.IGNORECASE)


@dataclass
class Indicacao:
    # O numero que VALE: o lido do papel, ou o que voce corrigiu na revisao.
    numero: int
    ano: int
    pagina_inicial: int
    pagina_final: int
    qtd_paginas: int
    # O numero como o OCR leu, sem correcao. Nunca muda entre rodadas (o OCR
    # erra igual toda vez), e por isso e ele que identifica a indicacao no
    # correcoes.json e no glossario. Sem essa separacao, corrigir o numero
    # mudaria a chave da propria correcao e ela se perderia na rodada
    # seguinte - a correcao viraria orfa da indicacao que corrigiu.
    numero_lido: int = 0
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
    # Data de apresentacao DESTA indicacao: a do carimbo "Lido na Sessão", no
    # verso. Cada uma tem a sua - num lote real ha 48 datas diferentes entre
    # 196 indicacoes. Vem quase sempre vazia, porque a data e escrita a mao no
    # carimbo e o OCR nao le letra de mao (ver src/datas.py): quem preenche e
    # voce, lendo a imagem da pagina do carimbo na propria tela.
    data_apresentacao: str = ""
    data_origem: str = ""
    data_suspeita: bool = False
    # Qual pagina do bloco tem o carimbo - e a imagem que a interface mostra
    # na hora de digitar a data. 0 = nao encontrada.
    pagina_carimbo: int = 0

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
    # Numero lido que nao conversa com nenhum vizinho da sequencia - o sinal
    # de OCR destruido no cabecalho. Ver detect.marcar_suspeitos.
    numero_suspeito: bool = False
    numero_corrigido: bool = False
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
    # QUAIS dos tres campos manuais resolvem esta indicacao: "ementa",
    # "autor", "confirmar". Preenchido por _classificar a partir dos motivos.
    # Existe para a tela de revisao saber quando a linha esta de fato
    # resolvida - antes ela considerava resolvido assim que UM dos tres campos
    # fosse preenchido, e a indicacao sumia da fila pela metade.
    falta: list[str] = field(default_factory=list)

    @property
    def identificador(self) -> str:
        """Como a indicacao e conhecida depois de corrigida - o que sai no
        CSV, no nome do PDF e no cadastro do SAPL."""
        return f"{self.numero}/{self.ano}"

    @property
    def identificador_lido(self) -> str:
        """A chave estavel: e por ela que a correcao e guardada e reencontrada
        na rodada seguinte, quando o OCR ler o mesmo numero errado de novo."""
        return f"{self.numero_lido or self.numero}/{self.ano}"

    @property
    def nome_arquivo(self) -> str:
        return f"{self.numero}-{self.ano}.pdf"

    @property
    def nome_arquivo_lido(self) -> str:
        """O nome que o PDF fatiado recebeu ANTES de o numero ser corrigido -
        e o arquivo que precisa ser renomeado."""
        return f"{self.numero_lido or self.numero}-{self.ano}.pdf"


def _texto_do_bloco(mapa: dict[int, str], ini: int, fim: int) -> str:
    return "\n".join(mapa.get(n, "") for n in range(ini, fim + 1))


def _ano_do_nome_arquivo(caminho: Path) -> int | None:
    m = _ANO_NO_NOME_RE.search(caminho.stem + ".pdf")
    return int(m.group(1)) if m else None


def processar_pasta(
    pasta_input: str | Path = INPUT_DIR,
    ano_padrao: int = 2023,
    ano_forcado: bool = False,
    usar_ollama: bool = True,
    gerar_pdfs: bool = True,
) -> list[Indicacao]:
    """Processa TODOS os PDFs de uma pasta e combina num unico resultado.

    ano_forcado=True (equivale a passar --ano no comando) faz ano_padrao
    valer para TODOS os arquivos, mesmo os que tem "@AAAA" no nome - um
    comando explicito tem que vencer uma inferencia automatica, nunca o
    contrario."""
    garantir_dirs()
    ids = carregar_ids()
    pasta_input = Path(pasta_input)

    # Aceita tanto uma pasta (o uso normal: processa tudo que tiver dentro)
    # quanto o caminho de um unico PDF (util para testar so um arquivo).
    #
    # ACIDENTE REAL que motivou o proximo "if": um bug na leitura dos
    # argumentos de linha de comando fez "--ano 2021" ser lido como se "2021"
    # fosse o CAMINHO da pasta de entrada. "2021" nao existe no disco, e
    # pasta_input.glob("*.pdf") numa pasta inexistente nao da erro nenhum -
    # so devolve vazio, IDENTICO a uma pasta vazia de verdade. O codigo la
    # embaixo tratou os dois casos do mesmo jeito e apagou 100 PDFs reais
    # (e o indicacoes.json inteiro) porque achou que o lote tinha sumido.
    #
    # A distincao que evita isso: pasta que EXISTE e esta vazia por engano
    # do usuario (voce apagou o PDF de input\) e uma coisa legitima - o
    # output deve mesmo refletir "nada". Caminho que NAO EXISTE e um erro de
    # digitacao ou de parsing - nunca deve ser tratado como "pasta vazia".
    if not pasta_input.exists():
        raise FileNotFoundError(
            f"{pasta_input} nao existe (nem arquivo, nem pasta). "
            "Isto e um erro de caminho, nao uma pasta vazia - nada foi "
            "apagado no output."
        )

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

    # O markdown e reconstruido do zero a cada execucao - e so leitura, sem
    # custo regenerar. Os PDFs fatiados (output/pdfs/) NAO: voce apaga cada
    # um deles a mao conforme anexa no SAPL, como forma de marcar "ja fiz
    # essa" - se recriassemos tudo aqui, essa marcacao se perderia toda vez
    # que voce rodasse o pipeline de novo. A limpeza deles e seletiva, feita
    # mais abaixo, depois que sabemos quais indicacoes ainda existem.
    if MARKDOWN_DIR.exists():
        shutil.rmtree(MARKDOWN_DIR)
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)

    todas: list[Indicacao] = []
    citacoes_todas: list[dict] = []
    origem_de: dict[tuple[int, int], str] = {}

    for caminho_pdf in pdfs:
        ano = ano_padrao if ano_forcado else (_ano_do_nome_arquivo(caminho_pdf) or ano_padrao)
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
    _renomear_pdfs_corrigidos(todas)
    for ind in todas:
        _classificar(ind)

    resolvedor.salvar_cache()
    resolvedor.salvar_aprendidos()

    # Limpeza seletiva do output/pdfs/: some so o que nao pertence a NENHUMA
    # indicacao atual (o PDF de origem saiu de input/) - nunca o que voce
    # apagou a mao mas cuja indicacao ainda existe.
    validos = {ind.nome_arquivo for ind in todas}
    removidos = 0
    for arquivo in PDFS_DIR.glob("*.pdf"):
        if arquivo.name not in validos:
            arquivo.unlink()
            removidos += 1
    if removidos:
        print(f"output/pdfs: {removidos} arquivo(s) orfao(s) removido(s) (indicacao nao existe mais)")

    if gerar_pdfs:
        print("Gerando PDF das indicacoes que ainda nao tem um ...")
        ja_gerados = _carregar_gerados()
        por_origem: dict[str, list[Indicacao]] = {}
        for ind in todas:
            por_origem.setdefault(ind.arquivo_origem, []).append(ind)
        for origem, inds in por_origem.items():
            _fatiar_pdf(origem, inds, ja_gerados)
        _salvar_gerados(ja_gerados)

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
    densidades = {p.numero: p.densidade for p in paginas}
    via_ocr = {p.numero for p in paginas if p.via_ocr}
    print(f"  {len(paginas)} paginas")

    inicios, citacoes = classificar_paginas(paginas)
    # Ordem obrigatoria: marcar os suspeitos ANTES de deduzir, senao um numero
    # lido errado vira ancora e estraga a deducao das vizinhas.
    inicios = inferir_numeros(marcar_suspeitos(inicios), ano)
    blocos = auditar(montar_blocos(inicios, len(paginas), ano))
    print(f"  {len(blocos)} indicacoes")

    indicacoes: list[Indicacao] = []
    barra = Progresso(len(blocos), prefixo="  ementa/autor ")
    for i, b in enumerate(blocos, start=1):
        texto = _texto_do_bloco(mapa, b.pagina_inicial, b.pagina_final)
        ind = Indicacao(
            numero=b.numero,
            numero_lido=b.numero,
            ano=b.ano,
            pagina_inicial=b.pagina_inicial,
            pagina_final=b.pagina_final,
            qtd_paginas=b.qtd_paginas,
            numero_inferido=b.numero_inferido,
            numero_suspeito=b.numero_suspeito,
            avisos_bloco=list(b.avisos),
            arquivo_origem=caminho_pdf,
            usou_ocr=any(n in via_ocr for n in range(b.pagina_inicial, b.pagina_final + 1)),
        )

        # A data que vale e a do carimbo "Lido na Sessão", no verso - e ela e
        # escrita a mao. O que da para fazer pela maquina e achar a PAGINA do
        # carimbo, para a interface mostrar essa imagem na hora de digitar.
        ind.pagina_carimbo = achar_pagina_do_carimbo(
            mapa, densidades, b.pagina_inicial, b.pagina_final
        )
        if ind.pagina_carimbo:
            # Tenta ler assim mesmo: se algum dia o carimbo vier datilografado
            # em vez de manuscrito, a data sai de graca. Nos lotes de 2021 isto
            # nao acerta nenhuma - e esta certo que nao acerte, porque chutar
            # uma data em documento oficial seria pior.
            achada = data_de_apresentacao(mapa.get(ind.pagina_carimbo, ""))
            if achada and achada.ano == ind.ano:
                ind.data_apresentacao = achada.formatada
                ind.data_origem = "carimbo"

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


def _recuperar_correcoes_antigas() -> None:
    """Uma vez so: puxa para o correcoes.json o que a versao antiga perdeu.

    Ate a correcao deste ciclo, cada rodada movia o glossario preenchido para
    glossario_anterior.csv e regravava o CSV em branco - o README chamava esse
    arquivo de "copia de seguranca que pode apagar sem medo", mas na pratica
    ele era o UNICO lugar onde a correcao digitada sobrava, e nunca era lido
    de volta. Se ele ainda existe e ainda nao ha correcoes.json, o trabalho
    que estava la volta para o lugar certo.
    """
    if CORRECOES.exists():
        return
    anterior = GLOSSARIO.with_name("glossario_anterior.csv")
    if not anterior.exists():
        return
    quantas = importar_do_glossario(anterior)
    if quantas:
        print(
            f"recuperadas {quantas} correcao(oes) de {anterior.name} "
            f"(perdidas pela versao antiga) -> {CORRECOES.name}"
        )


def _aplicar_correcoes_manuais(
    todas: list[Indicacao], ids: dict, resolvedor: ResolvedorAutor
) -> None:
    # Ordem importa: primeiro o que foi digitado direto na planilha entra na
    # memoria permanente, depois a memoria e que manda. Sem este passo, editar
    # o glossario.csv a mao (o caminho "avancado" do README) so valeria ate a
    # proxima regravacao do arquivo.
    _recuperar_correcoes_antigas()
    novas = importar_do_glossario(GLOSSARIO)
    if novas:
        print(f"{novas} correcao(oes) do glossario.csv guardadas em {CORRECOES.name}")

    manuais = ler_correcoes()
    if manuais:
        print(f"{len(manuais)} correcao(oes) manuais em {CORRECOES.name}")

    nomes = {a["id"]: a["nome"] for a in ids["autores"]}
    aprendidos: list[str] = []

    for ind in todas:
        manual = manuais.get(ind.identificador_lido)
        if not manual:
            continue
        # O numero vem primeiro: tudo depois dele (nome do PDF, cadastro no
        # SAPL) usa o valor corrigido.
        if manual.get("numero"):
            novo = int(manual["numero"])
            if novo != ind.numero:
                ind.numero = novo
                ind.numero_corrigido = True
                ind.motivos = [m for m in ind.motivos if not m.startswith("numero")]
        if manual.get("data"):
            ind.data_apresentacao = manual["data"]
            ind.data_origem = "manual"
            ind.data_suspeita = False
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


def _renomear_pdfs_corrigidos(todas: list[Indicacao]) -> None:
    """Corrigiu o numero na revisao? O PDF fatiado passa a se chamar assim.

    Sem isto voce anexaria "9-2021.pdf" na indicacao 1629/2021 - e como o
    anexo e feito a mao, o erro so apareceria na hora de escolher o arquivo,
    ou nem apareceria. O registro de gerados tambem migra de chave, senao o
    sistema acharia que a 1629 nunca teve PDF e recriaria um do zero.
    """
    corrigidas = [i for i in todas if i.numero_corrigido]
    if not corrigidas:
        return

    ja_gerados = _carregar_gerados()
    renomeados = 0
    for ind in corrigidas:
        antigo = PDFS_DIR / ind.nome_arquivo_lido
        novo = PDFS_DIR / ind.nome_arquivo
        if antigo.exists() and not novo.exists():
            try:
                antigo.rename(novo)
                renomeados += 1
            except OSError as e:
                print(f"  nao deu para renomear {antigo.name} -> {novo.name}: {e}")
        if ind.identificador_lido in ja_gerados:
            ja_gerados.discard(ind.identificador_lido)
            ja_gerados.add(ind.identificador)

    _salvar_gerados(ja_gerados)
    if renomeados:
        print(f"{renomeados} PDF(s) renomeado(s) pelo numero corrigido")


def _o_que_resolve(motivo: str) -> str:
    """Qual dos tres campos manuais resolve este motivo.

    As strings testadas aqui sao TODAS produzidas neste mesmo arquivo (ou em
    _extrair_um_pdf, logo acima) - nao sao texto de origem externa. "confirmar"
    e o destino de tudo que nao tem o que digitar: e o campo que quer dizer
    "eu olhei a pagina e esta certo assim".
    """
    # "numero:" (com dois pontos) e o que se corrige digitando o numero certo.
    # "numero deduzido pela sequencia" (sem dois pontos) e outra coisa: ali o
    # sistema chutou pela posicao e so quer que voce confirme olhando o papel.
    if motivo.startswith("numero:"):
        return "numero"
    if motivo.startswith("data:"):
        return "data"
    if motivo.startswith("ementa"):
        return "ementa"
    if motivo.startswith("autor"):
        return "autor"
    return "confirmar"


def _classificar(ind: Indicacao) -> None:
    """Decide se a indicacao pode ir sozinha para o SAPL."""
    motivos = list(ind.motivos)

    # Ementa escrita por voce nao passa pelo criterio de tamanho nem pelo de
    # confianca: o criterio existe para desconfiar do OCR, e aqui nao ha OCR
    # nenhum. Sem esta excecao, uma ementa curta legitima ("INDICA A PODA DE
    # ARVORE NA RUA X") ficaria pedindo revisao para sempre, mesmo depois de
    # transcrita corretamente do papel.
    manual = ind.ementa_metodo == "manual"

    if not ind.ementa:
        motivos.append("ementa vazia")
    elif not manual:
        if len(ind.ementa) < EMENTA_MIN:
            motivos.append(f"ementa curta demais ({len(ind.ementa)} caracteres)")
        elif len(ind.ementa) > EMENTA_MAX:
            motivos.append(f"ementa longa demais ({len(ind.ementa)} caracteres)")

    # Prefixo "ementa:" nao e enfeite: e o que _o_que_resolve usa para saber
    # que quem resolve isto e o campo de ementa, e nao o "ja conferi".
    if ind.confianca < CONFIANCA_MIN and not manual:
        motivos.append(f"ementa: confianca baixa ({ind.confianca})")
    if not ind.autor_id:
        if not any(m.startswith("autor") for m in motivos):
            motivos.append("autor nao identificado")
    # Sem data nao da para cadastrar: e o programa que preenche o campo no
    # SAPL agora, e a data tambem e o que destrava o select de autor (o SAPL
    # filtra pelo mandato vigente naquela data). Ela e escrita a mao no
    # carimbo do verso, entao vem de voce - a tela de conferencia mostra a
    # imagem do carimbo do lado do campo.
    if not ind.data_apresentacao:
        motivos.append("data: escrita a mao no carimbo - leia na imagem e digite")

    # Numero que nao conversa com a sequencia do lote. Nunca pode ir sozinho
    # para o SAPL: um numero errado vira registro oficial errado.
    if ind.numero_suspeito and not ind.numero_corrigido and not ind.confirmado_manual:
        motivos.append(
            f"numero: {ind.numero_lido} nao conversa com a sequencia do lote - "
            "confira no papel")
    # Estes dois nao tem campo de ementa/autor para corrigir - so o CONFIRMAR
    # (ind.confirmado_manual) resolve.
    if ind.numero_inferido and not ind.confirmado_manual and not ind.numero_corrigido:
        motivos.append("numero deduzido pela sequencia - confirmar no papel")
    if ind.qtd_paginas == 1 and not ind.confirmado_manual:
        motivos.append("bloco com 1 pagina - verso ausente no scan")

    ind.motivos = motivos
    # Ordem fixa (nao a de aparicao dos motivos) para a tela de revisao
    # mostrar sempre na mesma sequencia.
    resolvem = {_o_que_resolve(m) for m in motivos}
    ind.falta = [c for c in ("numero", "data", "ementa", "autor", "confirmar")
                 if c in resolvem]
    ind.status = "pronto" if not motivos else "revisao"


def _carregar_gerados() -> set[str]:
    if PDFS_GERADOS.exists():
        return set(json.loads(PDFS_GERADOS.read_text(encoding="utf-8")))
    return set()


def _salvar_gerados(chaves: set[str]) -> None:
    PDFS_GERADOS.write_text(
        json.dumps(sorted(chaves), ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _fatiar_pdf(
    caminho_pdf: str, indicacoes: list[Indicacao], ja_gerados: set[str]
) -> None:
    leitor = None  # so abre o PDF grande se realmente precisar fatiar algo
    barra = Progresso(len(indicacoes), prefixo=f"  {Path(caminho_pdf).name[:30]:<30} ")
    for ind in indicacoes:
        destino = PDFS_DIR / ind.nome_arquivo
        if destino.exists():
            ind.arquivo_pdf = str(destino)
            barra.avancar()
            continue
        if ind.identificador in ja_gerados:
            # Ja foi gerado antes e nao existe mais: voce apagou de
            # proposito depois de anexar no SAPL. Nao recriar.
            barra.avancar()
            continue

        if leitor is None:
            leitor = PdfReader(caminho_pdf)
        escritor = PdfWriter()
        for n in range(ind.pagina_inicial, ind.pagina_final + 1):
            escritor.add_page(leitor.pages[n - 1])
        with open(destino, "wb") as f:
            escritor.write(f)
        ind.arquivo_pdf = str(destino)
        ja_gerados.add(ind.identificador)
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
        "tipo_apresentacao", "data_apresentacao", "data_origem",
        "ementa", "autor_no_documento", "autor_origem",
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
                i.tipo_apresentacao,
                i.data_apresentacao + (" (CONFERIR)" if i.data_suspeita else ""),
                i.data_origem,
                i.ementa, i.autor_no_documento,
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

    # O glossario.csv e uma JANELA para as pendentes de agora, nao a memoria do
    # sistema: pode ser regravado a vontade porque tudo que voce digitou ja foi
    # para o correcoes.json (em _aplicar_correcoes_manuais, no inicio da
    # rodada) e volta preenchido logo abaixo.
    if not pendentes:
        escrever_glossario([], GLOSSARIO)
        escrever_revisao_md([], REVISAO_DIR / "REVISAO.md")
        print("nada pendente")
        return

    correcoes = ler_correcoes()
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
        # As colunas manuais voltam PREENCHIDAS com o que voce ja tinha
        # escrito. E o que diferencia "continuar de onde parou" de "comecar do
        # zero toda vez": uma indicacao que ainda precisa do autor nao apaga a
        # ementa que voce transcreveu na rodada passada.
        ja = correcoes.get(ind.identificador_lido, {})
        autor_manual = ja.get("autor_id") or ja.get("autor_id_invalido") or ""
        linhas.append({
            # A chave e o numero LIDO - e por ele que a correcao e reencontrada
            # na proxima rodada, quando o OCR errar igual de novo.
            "numero": ind.numero_lido or ind.numero,
            "ano": ind.ano,
            "paginas": f"{ind.pagina_inicial}-{ind.pagina_final}",
            "NUMERO_MANUAL": ja.get("numero", ""),
            "DATA_MANUAL": ja.get("data", ""),
            "data_lida_pela_maquina": (
                f"{ind.data_apresentacao} ({ind.data_origem})"
                if ind.data_apresentacao
                else (f"escrita a mao no carimbo da pagina {ind.pagina_carimbo}"
                      if ind.pagina_carimbo else "carimbo nao localizado")
            ),
            "imagens": ", ".join(imagens),
            "precisa": ", ".join(ind.falta),
            "motivo": " | ".join(ind.motivos),
            "ementa_lida_pela_maquina": ind.ementa,
            "sugestao_ollama_ementa": ind.sugestao_ementa_ollama,
            "EMENTA_MANUAL": ja.get("ementa", ""),
            "autor_lido_pela_maquina": (
                f"{ind.autor_no_documento or '(nada legivel)'}"
                f" -> {ind.autor_nome_sapl or '?'}"
            ),
            "sugestao_ollama_autor": ind.sugestao_autor_ollama,
            "AUTOR_ID_MANUAL": autor_manual,
            "CONFIRMAR": "sim" if ja.get("confirmado") else "",
        })

    escrever_glossario(linhas, GLOSSARIO)
    escrever_revisao_md(linhas, REVISAO_DIR / "REVISAO.md")
    print(f"{len(pendentes)} indicacoes para revisar em {GLOSSARIO}")
    print(f"leitura formatada em {REVISAO_DIR / 'REVISAO.md'} (abra o preview de Markdown)")
