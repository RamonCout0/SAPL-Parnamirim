"""Etapa 2: achar onde cada indicacao comeca e fatiar o PDF em blocos.

Regra de separacao (conforme especificado):
  a indicacao N comeca na pagina do seu cabecalho e termina na pagina anterior
  ao inicio da PROXIMA indicacao. Assim os casos especiais se resolvem sozinhos:
  se a 101 tem uma pagina extra de fotos, o bloco dela vai de 1 a 3 porque a
  102 so comeca na 4.

O detalhe que quebra a abordagem ingenua e que o OCR do scan falha de tres
formas, todas presentes no documento real:

  1. escreve o cabecalho errado  -> "Indicaçno n° 296/2023"  (regex tolerante)
  2. perde o cabecalho inteiro   -> a pagina 11 nao tem numero nenhum
  3. erra o ano                  -> "Indicação n' 294/ 2022"

Por isso a deteccao usa DOIS sinais independentes:

  SINAL A (numero)     - regex tolerante do cabecalho "Indicação n° N/ANO".
  SINAL B (estrutura)  - a formula de abertura que TODA primeira pagina tem:
                         "vereador com assento nesta egrégia Casa Legislativa".

O sinal B acha a pagina inicial mesmo sem numero legivel; o numero que falta
e deduzido pela posicao na sequencia (ver `inferir_numeros`).
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

from .textlayer import Pagina

# O numero da indicacao, com ou sem separador de milhar.
#
# BUG REAL, achado no lote de 2022: a partir da indicacao 1000 o papel escreve
# "Indicação n° 1.405/2022", com ponto. A versao antiga desta regex exigia os
# digitos colados - (\d{1,4}) - e o pedaco que pula o "n°" ([^0-9\n]) nao pode
# consumir digito, entao nao havia como casar: o cabecalho INTEIRO era
# ignorado. O efeito em cascata era o pior: sem cabecalho, a pagina so era
# reconhecida pela formula de abertura, o numero saia DEDUZIDO pela sequencia,
# e TODA indicacao de numero >= 1000 caia em revisao manual com "numero
# deduzido". Pior ainda, esses buracos entravam no calculo do passo da
# sequencia (ver inferir_numeros) e podiam deduzir numero errado para os
# vizinhos. Aceitar o separador resolve na origem.
#
# A alternativa com separador vem primeiro de proposito: em "1405" ela falha e
# o regex cai na segunda, mas em "1.405" a segunda sozinha pegaria so o "1".
_NUMERO = r"\d{1,3}[.\s]\d{3}|\d{1,4}"

# Tolerante ao OCR: "Indicação n°", "Indicaçno n°", "Indicação no", "Indicação n'".
CABECALHO_RE = re.compile(
    r"INDICA[CÇ]"                # radical estavel
    r"[\wÇÃÁÂÀÉÊÍÓÔÕÚçãáâàéêíóôõú]{0,4}"  # ao / ão / no / cao ...
    r"\s*[Nn]?[^0-9\n]{0,10}"    # n° / nº / n' / no / n. / N.º
    rf"({_NUMERO})\s*[/\-]\s*(\d{{4}})",
    re.IGNORECASE,
)


def numero_do_cabecalho(bruto: str) -> int:
    """"1.405" / "1 405" / "1405" -> 1405.

    O separador de milhar e do papel; o numero da indicacao e um inteiro so.
    Tudo que sai da CABECALHO_RE passa por aqui - nunca int() direto, senao
    "1.405" viraria ValueError ou, pior, um numero truncado.
    """
    return int(re.sub(r"[.\s]", "", bruto))

# Um cabecalho legitimo esta no topo da pagina. Mais fundo que isso e citacao
# no corpo do texto ("REITERA a indicação n° 498/2022"), que NAO abre bloco.
# Atencao: varias citacoes caem DENTRO dessa janela (posicao ~200), entao a
# regra que realmente decide e "vale o primeiro cabecalho da pagina".
JANELA_CABECALHO = 400

# Paginas de anexo repetem o numero da indicacao a que pertencem:
#   "ANEXO / Anexo à Indicação n° 233/2023. Registro fotográfico (demanda)..."
# Elas sao CONTINUACAO do bloco, nunca um inicio - se contadas como inicio,
# a indicacao aparece duplicada.
MARCADORES_ANEXO = ["anexo", "registro fotogr"]

# Formula de abertura. Presente na 1a pagina de toda indicacao, mesmo quando o
# cabecalho com o numero foi perdido pelo OCR.
MARCADORES_INICIO = [
    "assento nesta egr",          # "vereador com assento nesta egrégia Casa"
    "forma regimental",           # "subscrito na forma regimental em vigência"
    "casa legislativa",
]

# Em paginas de abertura real, esses marcadores aparecem bem cedo (medido:
# 108-214 caracteres). "casa legislativa" sozinho e perigoso porque tambem
# aparece em frases do CORPO da justificativa - "para que esta Casa
# Legislativa dê início ao debate..." - bem mais tarde no texto (medido: 374).
# Isso fez uma pagina de CONTINUACAO (justificativa + assinatura, sem verbo
# de abertura nenhum) ser lida como inicio de uma indicacao nova. Por isso o
# marcador so conta se aparecer perto do topo da pagina.
JANELA_MARCADOR_INICIO = 280

# O "cartao-resumo": a folha que a assessoria de alguns vereadores anexa DEPOIS
# da indicacao, repetindo o assunto em linhas curtas e com a foto do problema:
#
#     INDICAÇÃO: 465/2023 - 27/03/2023 - CÂMARA MUNICIPAL DE PARNAMIRIM/RN
#     VEREADORA: FATIVAN ALVES MOURA DE PAIVA
#     SOLICITAÇÃO: RECUPERAÇÃO DE TAMPA DE ESGOTO NA RUA PADRE OLIVEIRA ROLIM.
#     BAIRRO: LIBERDADE.
#
# Ela pertence a indicacao anterior e NAO abre bloco novo. "solicitacao:" com
# dois pontos e o que a identifica: medido no lote 500-401, aparece em 2 das
# 191 paginas - as duas cartoes, nenhuma com a formula juridica de abertura.
MARCADORES_CARTAO = ["solicitacao:"]
JANELA_CARTAO = 600

# Paginas de verso: a folha com o carimbo "Lido na Sessão" e a data.
MARCADORES_VERSO = [
    "lido na sess",
    "mesa diretora",
    "secretário",
    "secretario",
    "recebido",
]

# Abaixo disso a pagina nao tem texto suficiente para ser uma 1a pagina.
DENSIDADE_MINIMA_INICIO = 350

# Quanto um numero pode destoar dos vizinhos sem virar suspeita.
#
# Buracos de verdade existem (indicacao que simplesmente nao esta no lote), mas
# sao de poucas unidades. Erro de OCR em numero de quatro digitos erra por
# centenas ou milhares - casos reais do lote de 2021:
#   "Indicacao n° /617/2021"      -> leu 617,  era 1617  (erro de 1000)
#   "INDICAcAO N°. iG l9 / 2021"  -> leu 9,    era 1629  (erro de 1620)
# Uma folga de 20 passa longe dos buracos legitimos e pega esses de longe.
TOLERANCIA_SEQUENCIA = 20

# Quantos vizinhos olhar de cada lado. Dois, e nao um: com um so, um numero
# bom encostado num numero ruim era acusado junto com ele.
VIZINHOS_CONSIDERADOS = 2

# Quantas indicacoes um bloco pode ter engolido para a suspeita ainda valer
# (ver auditar). Acima disso o que houve foi outra coisa - uma virada de
# sequencia (o lote de 2021 vai ...792, 793, 601, 602...) ou um pedaco do lote
# que nao foi escaneado. Nenhuma das duas se resolve cortando o bloco.
MAX_ENGOLIDAS = 2


@dataclass
class Inicio:
    """Uma pagina identificada como comeco de indicacao."""

    pagina: int
    numero: int | None       # None quando o OCR perdeu o cabecalho
    ano: int | None
    tem_cabecalho: bool
    tem_estrutura: bool
    numero_inferido: bool = False
    # O numero foi lido, mas nao conversa com nenhum vizinho da sequencia -
    # quase sempre OCR destruido no cabecalho. Ver marcar_suspeitos.
    numero_suspeito: bool = False
    # Este inicio nao foi achado pela maquina: voce marcou na tela que a
    # indicacao comeca aqui (src/juncoes.py). Fica registrado porque quem
    # conferir depois precisa saber que a fronteira e humana, nao lida.
    corte_manual: bool = False
    # Em que pagina o numero foi lido, quando NAO foi no cabecalho da primeira
    # pagina e sim no cartao-resumo do fim do bloco. 0 = veio do cabecalho.
    # Fica registrado porque e um caminho menos obvio: quem conferir depois
    # precisa saber de onde o numero saiu.
    numero_do_cartao: int = 0


@dataclass
class Bloco:
    numero: int
    ano: int
    pagina_inicial: int
    pagina_final: int
    numero_inferido: bool = False
    numero_suspeito: bool = False
    numero_do_cartao: int = 0
    corte_manual: bool = False
    # Numeros que somem entre este bloco e o proximo, quando ha sinal de que
    # eles estao DENTRO deste bloco. Ver auditar. Vazio na maioria esmagadora.
    engoliu: list[int] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def identificador(self) -> str:
        return f"{self.numero}/{self.ano}"

    @property
    def qtd_paginas(self) -> int:
        return self.pagina_final - self.pagina_inicial + 1

    @property
    def faixa(self) -> str:
        if self.pagina_inicial == self.pagina_final:
            return str(self.pagina_inicial)
        return f"{self.pagina_inicial}-{self.pagina_final}"


def _tem(texto: str, marcadores: list[str]) -> bool:
    baixo = texto.lower()
    return any(m in baixo for m in marcadores)


def _sem_acento(texto: str) -> str:
    """Compara texto de OCR sem depender de acento.

    O OCR troca "SOLICITAÇÃO" por "SOLICITACAO" e "SOLICITAÇAO" conforme a
    qualidade da folha; a palavra e a mesma.
    """
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )


def _tem_formato_de_cartao(texto: str) -> bool:
    """A pagina tem a cara do cartao-resumo (ver MARCADORES_CARTAO)?"""
    topo = _sem_acento(texto[:JANELA_CARTAO])
    return any(m in topo for m in MARCADORES_CARTAO)


def _tem_estrutura_de_abertura(texto: str) -> bool:
    """MARCADORES_INICIO, mas so contam perto do topo da pagina - ver
    JANELA_MARCADOR_INICIO para o caso real que motivou isto."""
    baixo = texto[:JANELA_MARCADOR_INICIO].lower()
    return any(m in baixo for m in MARCADORES_INICIO)


def classificar_paginas(
    paginas: list[Pagina],
) -> tuple[list[Inicio], list[dict]]:
    """Decide, pagina por pagina, se ela abre uma indicacao nova.

    Retorna (inicios, citacoes_ignoradas).
    """
    inicios: list[Inicio] = []
    citacoes: list[dict] = []
    ultimo_numero: int | None = None

    for p in paginas:
        cab = None
        for m in CABECALHO_RE.finditer(p.texto):
            # "Anexo à Indicação n° 233/2023" logo antes do numero denuncia
            # pagina de anexo fotografico, que pertence ao bloco anterior.
            antes = p.texto[max(0, m.start() - 60) : m.start()].lower()
            eh_anexo = any(k in antes for k in MARCADORES_ANEXO)

            if cab is None and m.start() <= JANELA_CABECALHO and not eh_anexo:
                cab = m
                continue

            if eh_anexo:
                motivo = "anexo da propria indicacao"
            elif cab is not None:
                motivo = "citacao (o cabecalho da pagina ja foi lido)"
            else:
                motivo = "fundo da pagina"
            citacoes.append(
                {
                    "pagina": p.numero,
                    "numero": numero_do_cabecalho(m.group(1)),
                    "ano": int(m.group(2)),
                    "motivo": motivo,
                    "trecho": p.texto[
                        max(0, m.start() - 60) : m.start() + 90
                    ].replace("\n", " "),
                }
            )

        estrutura = _tem_estrutura_de_abertura(p.texto)
        verso = _tem(p.texto, MARCADORES_VERSO) and p.densidade < DENSIDADE_MINIMA_INICIO
        anexo_no_topo = any(k in p.texto[:200].lower() for k in MARCADORES_ANEXO)

        # "Cartao-resumo" (ver MARCADORES_CARTAO): a folha de resumo com foto
        # que vem DEPOIS da indicacao. Ela pertence ao bloco anterior; lida
        # como inicio, parte a mesma indicacao em dois.
        #
        # Sao dois sinais, e o primeiro foi acrescentado depois de um caso
        # real. O sinal antigo era so "o numero do cabecalho repete o do inicio
        # anterior", e ele falhava exatamente quando mais fazia falta: na
        # pagina 75 do lote 500-401 o OCR destruiu o cabecalho
        # ("inCilcação n °. 4bb/L11L3"), o inicio ficou SEM numero, e o
        # cartao-resumo da pagina 77 - que trazia "INDICAÇÃO: 465/2023" em
        # letra limpa - nao tinha com o que se comparar. Resultado: virou bloco
        # proprio, de uma pagina so, sem ementa e sem autor, e o lote terminou
        # com duas 465. O formato da propria pagina nao depende de nada disso.
        formato_cartao = _tem_formato_de_cartao(p.texto)
        eh_cartao_resumo = (
            cab is not None
            and not estrutura
            and (
                formato_cartao
                or (ultimo_numero is not None
                    and numero_do_cabecalho(cab.group(1)) == ultimo_numero)
            )
        )

        # Abre bloco se: tem cabecalho no topo (e nao for cartao-resumo), OU
        # tem a formula de abertura com texto suficiente (caso do cabecalho
        # perdido pelo OCR).
        if cab is not None and not eh_cartao_resumo:
            inicios.append(
                Inicio(
                    pagina=p.numero,
                    numero=numero_do_cabecalho(cab.group(1)),
                    ano=int(cab.group(2)),
                    tem_cabecalho=True,
                    tem_estrutura=estrutura,
                )
            )
            ultimo_numero = numero_do_cabecalho(cab.group(1))
        elif eh_cartao_resumo:
            numero_cartao = numero_do_cabecalho(cab.group(1))
            # O cartao diz, em letra digitada e limpa, o numero da indicacao a
            # que pertence. Quando o cabecalho da primeira pagina foi destruido
            # pelo OCR, ele e a MELHOR fonte que existe para aquele numero -
            # melhor que deduzir pela sequencia, que e o que sobraria. Antes
            # esse numero era jogado fora e a indicacao ia para revisao pedindo
            # um numero que estava escrito ali do lado.
            adotado = False
            if inicios and inicios[-1].numero is None:
                inicios[-1].numero = numero_cartao
                inicios[-1].ano = int(cab.group(2))
                inicios[-1].numero_do_cartao = p.numero
                ultimo_numero = numero_cartao
                adotado = True
            citacoes.append(
                {
                    "pagina": p.numero,
                    "numero": numero_cartao,
                    "ano": int(cab.group(2)),
                    "motivo": ("cartao-resumo: numero adotado pelo bloco anterior, "
                               "cujo cabecalho o OCR nao leu" if adotado else
                               "cartao-resumo da mesma indicacao (nao abre bloco novo)"),
                    "trecho": p.texto[:150].replace("\n", " "),
                }
            )
        elif (
            estrutura
            and not verso
            and not anexo_no_topo
            and p.densidade >= DENSIDADE_MINIMA_INICIO
        ):
            inicios.append(
                Inicio(
                    pagina=p.numero,
                    numero=None,
                    ano=None,
                    tem_cabecalho=False,
                    tem_estrutura=True,
                )
            )
            ultimo_numero = None

    return inicios, citacoes


def _passo_da_sequencia(conhecidos: list[tuple[int, int]]) -> int:
    """De quanto em quanto os numeros andam. Mediana, nao media: um numero
    lido errado desloca a media e nao mexe na mediana."""
    passos = [
        (n2 - n1) / (i2 - i1)
        for (i1, n1), (i2, n2) in zip(conhecidos, conhecidos[1:])
        if i2 != i1
    ]
    return round(statistics.median(passos)) if passos else -1


def marcar_suspeitos(inicios: list[Inicio]) -> list[Inicio]:
    """Marca numeros lidos que nao conversam com NENHUM vizinho.

    O caso real que motivou isto: o OCR leu "iG l9" onde estava "1.629" e o
    sistema registrou a indicacao como numero 9. Ela passou em todos os
    criterios (ementa boa, autor resolvido) e foi classificada como PRONTA -
    ou seja, iria para o SAPL como "Indicacao 9/2021", um registro oficial
    errado, sem ninguem ver. Numero fora da sequencia era so um aviso
    decorativo que nada lia.

    A regra e deliberadamente conservadora: so vira suspeita quem discorda de
    TODOS os vizinhos da janela. Duas consequencias que importam:

      - uma virada legitima de sequencia nao acusa nada. O lote real de 2021
        tem uma (...792, 793, depois 601, 602...): cada um concorda com o seu
        proprio lado.
      - o vizinho ruim nao derruba o bom. Olhar so o vizinho colado fazia o
        1628 ser acusado por estar ao lado do 9; com dois de cada lado ele
        encontra o 1630 e se confirma.
    """
    conhecidos = [
        (i, ini.numero) for i, ini in enumerate(inicios)
        if ini.numero is not None and not ini.numero_inferido
    ]
    if len(conhecidos) < 3:
        return inicios  # sequencia curta demais para saber o que e desvio

    passo = _passo_da_sequencia(conhecidos)
    for posicao, (i, numero) in enumerate(conhecidos):
        vizinhos = (
            conhecidos[max(0, posicao - VIZINHOS_CONSIDERADOS):posicao]
            + conhecidos[posicao + 1:posicao + 1 + VIZINHOS_CONSIDERADOS]
        )
        distancias = [
            abs(numero - (n + passo * (i - j))) for j, n in vizinhos
        ]
        if distancias and min(distancias) > TOLERANCIA_SEQUENCIA:
            inicios[i].numero_suspeito = True
    return inicios


def inferir_numeros(inicios: list[Inicio], ano_padrao: int) -> list[Inicio]:
    """Deduz os numeros perdidos pelo OCR a partir da posicao na sequencia.

    O documento vem numa progressao regular, e o SENTIDO dela sai dos proprios
    numeros - nada aqui supoe que o lote desce. Os dois sentidos aparecem de
    verdade: o lote de 2023 vem de 300 a 201 (passo -1) e o de 2022 vem de 601
    a 710 (passo +1). Achamos o passo pelos vizinhos conhecidos, com sinal, e
    projetamos sobre os buracos.

    Os numeros suspeitos ficam de fora das ancoras: um erro de leitura nao
    pode contaminar as vizinhas. Foi o que aconteceu no lote de 2021 - o "9"
    lido por engano virou ancora e a indicacao seguinte, cujo cabecalho o OCR
    perdeu de vez, foi deduzida como "10" em vez de 1630.
    """
    conhecidos = [
        (i, ini.numero) for i, ini in enumerate(inicios)
        if ini.numero and not ini.numero_suspeito
    ]
    if len(conhecidos) < 2:
        return inicios

    # Sem "or -1": um passo zero significa que a sequencia nao progride, e
    # nesse caso a deducao repete o numero do vizinho - o que o detector de
    # numero repetido pega e manda para conferencia. Forcar -1 ali, como era
    # antes, inventava uma sequencia decrescente que ninguem mediu: numero
    # errado com cara de certo, que e o unico tipo que chega ao SAPL calado.
    passo = _passo_da_sequencia(conhecidos)

    for i, ini in enumerate(inicios):
        if ini.numero is not None:
            continue
        # Ancora no vizinho conhecido mais proximo.
        anterior = [(j, n) for j, n in conhecidos if j < i]
        seguinte = [(j, n) for j, n in conhecidos if j > i]
        candidatos = []
        if anterior:
            j, n = anterior[-1]
            candidatos.append(n + passo * (i - j))
        if seguinte:
            j, n = seguinte[0]
            candidatos.append(n + passo * (i - j))
        if candidatos and all(c == candidatos[0] for c in candidatos):
            ini.numero = candidatos[0]
            ini.ano = ano_padrao
            ini.numero_inferido = True
        elif candidatos:
            # Vizinhos discordam: fica o do lado anterior, mas marcado.
            ini.numero = candidatos[0]
            ini.ano = ano_padrao
            ini.numero_inferido = True

    return inicios


def montar_blocos(
    inicios: list[Inicio], total_paginas: int, ano_padrao: int
) -> list[Bloco]:
    """Cada inicio manda ate a pagina anterior ao proximo inicio."""
    blocos: list[Bloco] = []
    for i, ini in enumerate(inicios):
        if ini.numero is None:
            continue
        fim = inicios[i + 1].pagina - 1 if i + 1 < len(inicios) else total_paginas
        avisos: list[str] = []

        # O ano do cabecalho e ruido de OCR frequente ("294/ 2022" onde o
        # documento todo e de 2023). O ano do lote manda.
        ano = ini.ano or ano_padrao
        if ano != ano_padrao:
            avisos.append(f"OCR leu ano {ano}; corrigido para {ano_padrao}")
            ano = ano_padrao

        if ini.numero_inferido:
            avisos.append("numero DEDUZIDO pela sequencia (cabecalho ilegivel) - confirmar")
        if ini.numero_do_cartao:
            avisos.append(
                f"numero lido no cartao-resumo da pagina {ini.numero_do_cartao} "
                "(o cabecalho da primeira pagina saiu ilegivel)"
            )
        if ini.corte_manual:
            avisos.append(
                "inicio marcado por voce na tela de conferencia (a maquina nao "
                "viu cabecalho nesta pagina)"
            )

        blocos.append(
            Bloco(
                numero=ini.numero,
                ano=ano,
                pagina_inicial=ini.pagina,
                pagina_final=fim,
                numero_inferido=ini.numero_inferido,
                numero_suspeito=ini.numero_suspeito,
                numero_do_cartao=ini.numero_do_cartao,
                corte_manual=ini.corte_manual,
                avisos=avisos,
            )
        )
    return blocos


def auditar(blocos: list[Bloco]) -> list[Bloco]:
    """Marca o que precisa de olho humano antes de subir pro SAPL."""
    # Tamanho normal de bloco NESTE lote - a base da suspeita de bloco duplo,
    # logo abaixo. Mediana e nao media: um bloco gigante (o proprio que engoliu
    # outro) nao pode subir a referencia e se absolver sozinho.
    tipico = statistics.median([b.qtd_paginas for b in blocos]) if blocos else 0

    vistos: dict[int, int] = {}
    for i, b in enumerate(blocos):
        if b.numero in vistos:
            b.avisos.append(f"numero repetido (ja visto na pagina {vistos[b.numero]})")
        vistos[b.numero] = b.pagina_inicial

        if b.qtd_paginas > 4:
            b.avisos.append(f"{b.qtd_paginas} paginas - conferir se falta um inicio")
        if b.qtd_paginas == 1:
            b.avisos.append("1 pagina - verso pode nao ter sido escaneado")

        if i + 1 < len(blocos):
            passo = blocos[i + 1].numero - b.numero
            if passo not in (1, -1):
                b.avisos.append(f"sequencia salta para {blocos[i+1].numero}")

            # Bloco que ENGOLIU a indicacao seguinte: a maquina nao achou o
            # inicio dela (cabecalho destruido pelo OCR) e as paginas das duas
            # viraram um bloco so. E o pior erro de fronteira que existe aqui,
            # porque nao reclama em lugar nenhum: a indicacao engolida nao
            # chega a ser criada, entao nada a cobra, e o PDF que sobe para o
            # SAPL leva dentro um documento que nao e o da materia. Caso real:
            # a 610 e a 609.
            #
            # A assinatura tem DUAS metades, e as duas sao necessarias:
            #   - a sequencia pula (610 -> 608: a 609 nao esta em bloco nenhum);
            #   - o bloco esta com o dobro do tamanho normal do lote, porque
            #     leva as duas indicacoes dentro.
            # So o pulo nao serve: buraco de verdade existe (indicacao que nao
            # foi escaneada) e deixa o bloco do tamanho de sempre - acusar todo
            # pulo mandaria para a conferencia dezenas de blocos corretos. So o
            # tamanho tambem nao: anexo fotografico engorda bloco sem esconder
            # nada, e por isso ja tem o aviso proprio acima.
            if 1 < abs(passo) <= MAX_ENGOLIDAS + 1 and b.qtd_paginas >= 2 * tipico:
                sentido = 1 if passo > 0 else -1
                b.engoliu = list(
                    range(b.numero + sentido, blocos[i + 1].numero, sentido)
                )
                b.avisos.append(
                    f"{b.qtd_paginas} paginas e a indicacao "
                    + ", ".join(map(str, b.engoliu))
                    + " nao aparece em bloco nenhum - pode estar dentro deste"
                )

    numeros = [b.numero for b in blocos]
    if numeros:
        faltando = sorted(set(range(min(numeros), max(numeros) + 1)) - set(numeros))
        if faltando:
            blocos[0].avisos.append(
                "ausentes no documento: " + ", ".join(map(str, faltando))
            )
    return blocos
