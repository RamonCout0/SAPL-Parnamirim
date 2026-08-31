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
from datetime import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from . import ollama_client
from .autores import ResolvedorAutor
from .campos import extrair_ementa, extrair_nome_autor, problemas_na_ementa
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
from .juncoes import JUNCOES
from .juncoes import aplicar as aplicar_juncoes
from .progresso import Progresso
from .revisao import (
    CORRECOES,
    correcao_de,
    escrever_glossario,
    escrever_referencia_autores,
    escrever_revisao_md,
    exportar_paginas_png,
    importar_do_glossario,
    ler_correcoes,
    ordenar_glossario,
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

# Um nome de arquivo com "@AAAA" define o ano so daquele arquivo, sem precisar
# passar --ano toda vez. Sem isso no nome, vale o --ano do comando (ou 2023).
#
# O "@AAAA" pode estar em QUALQUER posicao do nome, nao so no fim. A versao
# anterior exigia que o nome TERMINASSE em "@AAAA.pdf" e, com isso, falhava em
# silencio em todo lote dividido em partes - justamente o formato da maioria
# dos arquivos reais:
#     TODAS_INDICACOES@2010.p1.pdf
#     TODAS_INDICACOES@2013.P1.pdf
#     TODAS_INDICACOES_ATUALIZADAS@2019_P10_frenteverso.pdf
# Medido em 26/08/2026 sobre os 78 PDFs de 2009-2020: 46 deles (59%) nao
# casavam e caiam sem aviso nenhum no ano padrao 2023 - ou seja, indicacoes de
# 2010 seriam cadastradas no SAPL como se fossem de 2023. Erro silencioso e
# pior que erro barulhento: nada no output denunciava a troca.
#
# Quando ha mais de um "@AAAA" no nome, vale o ULTIMO - o mais especifico.
_ANO_NO_NOME_RE = re.compile(r"@(\d{4})(?!\d)", re.IGNORECASE)


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
    # Voce olhou a indicacao e disse: ela nao tem autor individual. E o caso
    # das assinadas por todos os vereadores ("Os Vereadores da Camara ...
    # INDICAM", com tres paginas de assinaturas). Diferente de autor_id == 0,
    # que quer dizer "a maquina nao conseguiu ler" e tem de parar e chamar
    # voce - por isso sao dois campos e nao um.
    sem_autor: bool = False
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

    # A fronteira deste bloco foi marcada por voce, nao lida pela maquina
    # (config/juncoes.json, secao "cortes").
    corte_manual: bool = False
    # Indicacoes que somem entre este bloco e o proximo, quando ha sinal de que
    # elas estao DENTRO deste bloco - o caso da 610 que engoliu a 609. Ver
    # detect.auditar. Vira motivo de conferencia em _classificar.
    engoliu: list[int] = field(default_factory=list)

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
    def paginas(self) -> str:
        """O intervalo de paginas do bloco, como sai na coluna do glossario.
        E o que distingue duas indicacoes lidas com o mesmo numero."""
        return f"{self.pagina_inicial}-{self.pagina_final}"

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
    achados = _ANO_NO_NOME_RE.findall(caminho.stem)
    if not achados:
        return None
    # O ultimo "@AAAA" vence: e o mais especifico quando o nome tem mais de um.
    ano = int(achados[-1])
    # Ano fora da faixa plausivel nao e ano: e numero de protocolo que por
    # acaso veio depois de "@". Melhor devolver None e deixar o --ano decidir
    # do que cadastrar o lote inteiro num ano inventado.
    return ano if 1990 <= ano <= 2100 else None


def processar_pasta(
    pasta_input: str | Path = INPUT_DIR,
    ano_padrao: int = 2023,
    ano_forcado: bool = False,
    usar_ollama: bool = True,
    gerar_pdfs: bool = True,
    force_pdfs: bool = False,
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
    origem_de: dict[int, str] = {}

    for caminho_pdf in pdfs:
        ano = ano_padrao if ano_forcado else (_ano_do_nome_arquivo(caminho_pdf) or ano_padrao)
        print(f"\n--- {caminho_pdf.name} (ano {ano}) ---")
        indicacoes, citacoes = _extrair_um_pdf(str(caminho_pdf), ano, usar_ollama, resolvedor)
        citacoes_todas.extend(citacoes)
        for ind in indicacoes:
            origem_de[id(ind)] = caminho_pdf.name
        todas.extend(indicacoes)

    print(f"\n{len(todas)} indicacoes ao todo. Aplicando correcoes do glossario ...")
    _aplicar_correcoes_manuais(todas, ids, resolvedor)
    # A conferencia de numero repetido vem DEPOIS das correcoes, sobre os
    # numeros que valem. Antes delas, a colisao que voce acabou de resolver
    # ("esta e a 708") continuaria aparecendo em toda rodada, porque as duas
    # ainda seriam 706 neste ponto - e a indicacao certa nunca sairia da fila.
    _marcar_numeros_repetidos(todas, origem_de)
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
            _fatiar_pdf(origem, inds, ja_gerados, force=force_pdfs)
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
    # As fronteiras que voce corrigiu a mao entram AQUI, antes de qualquer
    # conta sobre a sequencia: um bloco que nao devia existir nao pode virar
    # ancora nem buraco no calculo do passo, e um que devia existir precisa
    # estar no lugar dele antes de a deducao contar as posicoes.
    antes = {ini.pagina for ini in inicios}
    inicios = aplicar_juncoes(inicios, Path(caminho_pdf).name)
    depois = {ini.pagina for ini in inicios}
    # Contadas por pagina, e nao pelo tamanho da lista: juntar e cortar podem
    # acontecer no mesmo arquivo, e ai a diferenca de tamanho daria zero e a
    # linha nao apareceria - some justamente no caso em que ela mais importa.
    if antes - depois:
        print(f"  {len(antes - depois)} bloco(s) juntados ao anterior "
              f"(marcados por voce em {JUNCOES.name})")
    if depois - antes:
        print(f"  {len(depois - antes)} bloco(s) abertos por corte manual, "
              f"nas paginas {', '.join(map(str, sorted(depois - antes)))} "
              f"({JUNCOES.name})")
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
            corte_manual=b.corte_manual,
            engoliu=list(b.engoliu),
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


def _marcar_numeros_repetidos(
    todas: list[Indicacao], origem_de: dict[int, str]
) -> None:
    """Dois blocos com o mesmo numero: os DOIS vao para conferencia.

    Caso real, no lote de 2022 (110 indicacoes, numeros 601 a 710): as paginas
    221 e 225 trazem AS DUAS "INDICAÇÃO N° 706/2022" impresso, e a sequencia do
    arquivo vai 706, 707, 706, 709 - o 708 nao aparece em pagina nenhuma. Nao e
    erro de leitura: o numero esta errado no PAPEL, e so quem le as duas
    paginas pode dizer qual delas e a 708.

    O estrago que isso faz quando ninguem ve:

      - o cadastro sai no SAPL com um numero que ja e de outra indicacao;
      - e com o PDF errado anexado, porque output/pdfs/706-2022.pdf ja existia
        e _fatiar_pdf nao sobrescreve arquivo que ja esta la.

    Marcar so o segundo bloco (como era antes) nao basta: olhando um so nao da
    para saber qual e qual. Quem decide e quem ve as duas imagens, entao as
    duas param.

    O prefixo "numero:" nao e enfeite - e ele que faz a tela de conferencia
    EXIGIR o numero digitado, em vez de aceitar um "ja conferi" e seguir com o
    numero repetido.
    """
    grupos: dict[tuple[int, int], list[Indicacao]] = {}
    for ind in todas:
        grupos.setdefault((ind.numero, ind.ano), []).append(ind)

    for (numero, ano), grupo in grupos.items():
        if len(grupo) < 2:
            continue
        arquivos = sorted({origem_de.get(id(i), "?") for i in grupo})
        onde = (f"duas vezes em {arquivos[0]}" if len(arquivos) == 1
                else "em " + " e ".join(arquivos))
        for ind in grupo:
            ind.motivos.append(
                f"numero: {numero}/{ano} aparece {onde} "
                f"(paginas " + ", ".join(
                    f"{i.pagina_inicial}-{i.pagina_final}" for i in grupo)
                + ") - leia o numero na imagem e digite o certo"
            )


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

    # Duas indicacoes com o mesmo numero lido nao podem dividir a mesma chave,
    # senao a correcao de uma cai nas duas (ver revisao.chave_da_correcao).
    repetidas: dict[str, int] = {}
    for ind in todas:
        repetidas[ind.identificador_lido] = repetidas.get(ind.identificador_lido, 0) + 1

    for ind in todas:
        manual = correcao_de(
            manuais, ind.numero_lido or ind.numero, ind.ano, ind.paginas,
            ambigua=repetidas.get(ind.identificador_lido, 0) > 1,
        )
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
        if manual.get("sem_autor"):
            ind.sem_autor = True
            ind.autor_id = 0
            ind.autor_nome_sapl = ""
            ind.autor_origem = "sem autor (você conferiu)"
            ind.motivos = [m for m in ind.motivos if not m.startswith("autor")]
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
    # De quem e cada nome de arquivo DEPOIS das correcoes. Serve para nunca
    # levar embora o PDF de outra indicacao: quando dois blocos vem com o mesmo
    # numero no papel e voce corrige um deles para 708, o arquivo 706-2022.pdf
    # continua sendo da 706 de verdade - renomea-lo deixaria a 706 sem PDF e
    # daria a 708 as paginas erradas, documento errado em registro oficial.
    donos = {i.nome_arquivo for i in todas}
    for ind in corrigidas:
        antigo = PDFS_DIR / ind.nome_arquivo_lido
        novo = PDFS_DIR / ind.nome_arquivo
        if antigo.name in donos:
            print(f"  {antigo.name} e de outra indicacao - nao renomeei; "
                  f"{novo.name} sera gerado do zero")
            continue
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
        # Ementa com o tamanho certo e a estrutura certa ainda pode ter
        # "INbICACÁO" no meio. Esses avisos apontam o trecho suspeito, para a
        # conferencia ir direto ao ponto em vez de reler tudo. So valem para
        # ementa vinda do OCR: o que voce transcreveu nao tem o que auditar.
        motivos.extend(problemas_na_ementa(ind.ementa))

    # Prefixo "ementa:" nao e enfeite: e o que _o_que_resolve usa para saber
    # que quem resolve isto e o campo de ementa, e nao o "ja conferi".
    if ind.confianca < CONFIANCA_MIN and not manual:
        motivos.append(f"ementa: confianca baixa ({ind.confianca})")
    # sem_autor e uma resposta dada por voce, nao a falta de uma. Sem essa
    # distincao, so haveria duas saidas ruins: ou esta indicacao ficava presa
    # na fila para sempre, ou o autor deixava de ser exigido de todo mundo e
    # qualquer assinatura ilegivel passava calada.
    if not ind.autor_id and not ind.sem_autor:
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

    # Bloco sob suspeita de ter engolido a indicacao seguinte (detect.auditar).
    # Nao ha campo que resolva isso digitando: ou voce olha as imagens e diz
    # "esta certo assim" (CONFIRMAR), ou marca na tela onde a outra comeca e o
    # proximo processamento corta o bloco em dois. Sem este motivo, o bloco ia
    # calado para o SAPL - com o PDF errado anexado e uma indicacao a menos no
    # lote, que e o unico erro daqui que ninguem descobre depois.
    if ind.engoliu and not ind.confirmado_manual:
        quais = ", ".join(str(n) for n in ind.engoliu)
        motivos.append(
            f"bloco: {ind.qtd_paginas} paginas e a indicacao {quais} nao aparece "
            "em lugar nenhum do lote - veja nas imagens se ela nao comeca no "
            "meio deste bloco"
        )

    ind.motivos = motivos
    # Ordem fixa (nao a de aparicao dos motivos) para a tela de revisao
    # mostrar sempre na mesma sequencia.
    resolvem = {_o_que_resolve(m) for m in motivos}
    ind.falta = [c for c in ("numero", "data", "ementa", "autor", "confirmar")
                 if c in resolvem]
    ind.status = "pronto" if not motivos else "revisao"


def _carregar_gerados() -> set[str]:
    if PDFS_GERADOS.exists():
        try:
            return set(json.loads(PDFS_GERADOS.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            # Arquivo corrompido ou inacessível: preserva o original como backup
            # e substitui por um JSON vazio para nao travar o processamento.
            try:
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                backup = PDFS_GERADOS.with_name(PDFS_GERADOS.name + f".corrupt-{ts}")
                shutil.move(str(PDFS_GERADOS), str(backup))
                print(f"AVISO: {PDFS_GERADOS.name} estava corrompido; movido para {backup.name}")
            except Exception:
                print(f"AVISO: problema ao mover {PDFS_GERADOS.name}, erro: {e}")
            try:
                PDFS_GERADOS.write_text("[]", encoding="utf-8")
            except Exception:
                pass
            return set()
    return set()


def _salvar_gerados(chaves: set[str]) -> None:
    PDFS_GERADOS.write_text(
        json.dumps(sorted(chaves), ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _paginas_no_arquivo(caminho: Path) -> int | None:
    """Quantas paginas tem um PDF ja fatiado. None quando nao da para saber.

    Nao da para saber acontece de verdade: arquivo meio escrito por uma rodada
    interrompida, PDF aberto no visualizador. Nesses casos o certo e nao mexer
    - refazer por engano apagaria o arquivo que o usuario esta olhando.
    """
    try:
        return len(PdfReader(str(caminho)).pages)
    except Exception:
        return None


def _fatiar_pdf(
    caminho_pdf: str, indicacoes: list[Indicacao], ja_gerados: set[str], *, force: bool = False
) -> None:
    leitor = None  # so abre o PDF grande se realmente precisar fatiar algo
    refeitos: list[str] = []
    barra = Progresso(len(indicacoes), prefixo=f"  {Path(caminho_pdf).name[:30]:<30} ")
    for ind in indicacoes:
        destino = PDFS_DIR / ind.nome_arquivo
        # O PDF ja existe - mas as paginas do bloco podem ter mudado desde que
        # ele foi gerado, e mudam exatamente quando voce corrige uma fronteira
        # (juntar/cortar, config/juncoes.json). Sem conferir a contagem, cortar
        # a 609 de dentro da 610 nao adiantava nada: o 610-2023.pdf continuava
        # sendo o antigo, com as duas indicacoes dentro, porque o arquivo
        # existia e era pulado. Documento errado em cadastro oficial, calado.
        refazer = False
        if destino.exists():
            tem = _paginas_no_arquivo(destino)
            if tem is None or tem == ind.qtd_paginas:
                ind.arquivo_pdf = str(destino)
                barra.avancar()
                continue
            refeitos.append(f"{destino.name}: {tem} -> {ind.qtd_paginas} paginas")
            refazer = True

        # Ja foi gerado antes e nao existe mais: voce apagou de proposito
        # depois de anexar no SAPL. Nao recriar - mas a excecao e o refazer
        # acima, que so acontece com arquivo em maos e com a contagem errada.
        if not refazer and not force and ind.identificador in ja_gerados:
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

    # Depois da barra, nunca no meio dela: a barra reescreve a propria linha
    # com "\r" e um print no meio deixa o terminal picotado.
    for aviso in refeitos:
        print(f"  refeito porque o bloco mudou de tamanho - {aviso}")


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
    # Mesma contagem de _aplicar_correcoes_manuais, e pelo mesmo motivo: com
    # numero lido repetido, a chave da correcao leva as paginas junto.
    repetidas: dict[str, int] = {}
    for ind in indicacoes:
        repetidas[ind.identificador_lido] = repetidas.get(ind.identificador_lido, 0) + 1

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
        ja = correcao_de(
            correcoes, ind.numero_lido or ind.numero, ind.ano, ind.paginas,
            ambigua=repetidas.get(ind.identificador_lido, 0) > 1,
        )
        autor_manual = ja.get("autor_id") or ja.get("autor_id_invalido") or ""
        linhas.append({
            # A chave e o numero LIDO - e por ele que a correcao e reencontrada
            # na proxima rodada, quando o OCR errar igual de novo.
            "numero": ind.numero_lido or ind.numero,
            "ano": ind.ano,
            "paginas": f"{ind.pagina_inicial}-{ind.pagina_final}",
            "arquivo": Path(ind.arquivo_origem).name,
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
            "SEM_AUTOR": "sim" if ja.get("sem_autor") else "",
            "CONFIRMAR": "sim" if ja.get("confirmado") else "",
        })

    # Em ordem de indicacao, e nao na ordem em que os PDFs foram varridos: os
    # dois arquivos daqui sao para LER, e a varredura entrega 2023 embaralhado
    # (os arquivos entram por nome, e dentro de varios a numeracao desce). Vale
    # para a tela de conferencia, que ordena por conta propria, e tambem para
    # quem abre o REVISAO.md ou o CSV no Excel - esses nao teriam como ordenar.
    linhas = ordenar_glossario(linhas)
    escrever_glossario(linhas, GLOSSARIO)
    escrever_revisao_md(linhas, REVISAO_DIR / "REVISAO.md")
    print(f"{len(pendentes)} indicacoes para revisar em {GLOSSARIO}")
    print(f"leitura formatada em {REVISAO_DIR / 'REVISAO.md'} (abra o preview de Markdown)")
