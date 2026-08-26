"""Casar o nome assinado no documento com o ID do select "Autor" do SAPL.

Estrategia em tres degraus, do mais barato e confiavel para o mais caro:

  1. cache/alias   - nome ja resolvido antes, ou alias escrito no sapl_ids.json.
                     Custo zero, acerto garantido.
  2. rapidfuzz     - semelhanca textual. Resolve "Wolney Freitas de Azevedo
                     França" -> "Wolney França" com folga.
  3. Ollama        - so quando a semelhanca textual e ambigua. E o caso de
                     "Ana Carolina Carvalho de Lima Pires" -> "Carol Pires",
                     onde nenhum algoritmo de string acerta mas o modelo sabe
                     que Carol e apelido de Carolina.

Se os tres degraus falharem, devolve id 0 e a indicacao vai para revisao
manual. Nunca chuta.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz, process

from . import ollama_client
from .config import CONFIG_DIR, OUTPUT_DIR

# Acima disso o casamento textual e aceito direto.
LIMITE_ACEITE = 88

CACHE = OUTPUT_DIR / "cache_autores.json"
# Nomes civis que voce confirmou no glossario. Cresce a cada rodada e vale
# para todos os lotes seguintes: "Hamilton Rademacker Pereira" preenchido uma
# vez resolve as outras 7 indicacoes dele sozinho.
APRENDIDOS = CONFIG_DIR / "aliases_aprendidos.json"


# Titulos que vem antes do nome e nao servem para identificar a pessoa.
HONORIFICOS = {
    "dr", "dra", "doutor", "doutora", "professor", "professora", "prof",
    "profa", "sr", "sra", "senhor", "senhora", "vereador", "vereadora",
}

# Palavras do timbre, do cabecalho e do rodape - o que o OCR pega quando a
# assinatura sai ilegivel. Nenhuma delas e nome de gente.
#
# Existe por causa de um estrago real: na 329/2023 o OCR leu "CAMARA'MUNICIPAL"
# no lugar da assinatura, a correcao manual apontou Gustavo Negocio, e o
# aprender() gravou isso como alias permanente. Como esse texto esta no timbre
# de TODA indicacao, qualquer PDF com assinatura ilegivel passaria a resolver
# para Gustavo Negocio com "certeza alta", origem alias-exato, sem nenhum
# aviso. Nome civil se aprende da assinatura, nunca do papel timbrado.
PALAVRAS_DE_TIMBRE = {
    "camara", "municipal", "parnamirim", "estado", "rio", "grande", "norte",
    "poder", "legislativo", "gabinete", "plenario", "mesa", "diretora",
    "indicacao", "requerimento", "excelentissimo", "excelentissima",
    "presidente", "sala", "sessoes", "sessao",
}

# Ligacoes que aparecem no meio de nome de gente E no meio de timbre, entao
# nao contam para nenhum dos dois lados. "de", "da", "do" tem duas letras e ja
# caem fora sozinhas; "das" e "dos" tem tres e passavam - era por "das" que
# "Sala das Sessoes" escapava do filtro.
CONECTIVOS = {"das", "dos", "com", "por", "para", "sob", "sobre", "seu", "sua"}


def _normalizar(s: str) -> str:
    s = "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(s.replace(".", " ").replace("-", " ").split())


def _primeiro_nome(s: str) -> str:
    """Primeiro nome de verdade, pulando titulo. "Dr. César Maia" -> "cesar"."""
    for token in _normalizar(s).split():
        if token not in HONORIFICOS and len(token) >= 3:
            return token
    return ""


def _e_nome_de_gente(s: str) -> bool:
    """Sobrou alguma palavra que possa ser nome de pessoa?

    Corta em qualquer coisa que nao seja letra ou numero de proposito: o OCR
    gruda palavras com apostrofo e pontuacao inventada ("CAMARA'MUNICIPAL"
    vira um token so), e sem isso o timbre passava batido.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", _normalizar(s)) if len(t) >= 3]
    vazias = PALAVRAS_DE_TIMBRE | HONORIFICOS | CONECTIVOS
    return any(t not in vazias for t in tokens)


class ResolvedorAutor:
    def __init__(self, ids: dict, usar_ollama: bool = True):
        self.usar_ollama = usar_ollama
        self.parlamentares = [a for a in ids["autores"] if a.get("parlamentar")]
        self.cache: dict[str, dict] = {}
        if CACHE.exists():
            self.cache = json.loads(CACHE.read_text(encoding="utf-8"))
        # Chaves de fato consultadas nesta rodada. salvar_cache() usa isto
        # para podar entradas de PDFs que ja nao estao mais em input/ - sem
        # isso o cache so cresce, mesmo depois de um PDF ser removido.
        self.chaves_vistas: set[str] = set()

        # chave normalizada -> registro do autor
        #
        # `if a.get("id")` exclui os vereadores marcados `sem_cadastro_no_sapl`,
        # que ficam todos com id 0. Sem o filtro eles colidiriam entre si nesta
        # chave e um deles viraria "o autor de id 0" para o aprender().
        self.por_id = {a["id"]: a for a in ids["autores"] if a.get("id")}
        self.por_texto: dict[str, dict] = {}
        for a in self.parlamentares:
            self.por_texto[_normalizar(a["nome"])] = a
            for al in a.get("aliases", []):
                self.por_texto[_normalizar(al)] = a

        # token -> ids de parlamentares em que aquele token aparece, em
        # qualquer posicao do nome ou dos aliases. Usado para desarmar o
        # casamento por chave de UMA palavra (ver _chave_ambigua).
        self.donos_do_token: dict[str, set[int]] = {}
        for a in self.parlamentares:
            for grafia in [a["nome"], *a.get("aliases", [])]:
                for token in _normalizar(grafia).split():
                    if len(token) >= 3:
                        self.donos_do_token.setdefault(token, set()).add(id(a))

        # primeiro nome -> parlamentares que o compartilham. Serve para o
        # atalho "primeiro nome basta", que so vale quando e unico: "Michael"
        # aponta para Borges E Diniz, "Professor" para tres pessoas.
        self.por_primeiro_nome: dict[str, list[dict]] = {}
        for a in self.parlamentares:
            for grafia in [a["nome"], *a.get("aliases", [])]:
                pn = _primeiro_nome(grafia)
                if not pn:
                    continue
                donos = self.por_primeiro_nome.setdefault(pn, [])
                if a not in donos:
                    donos.append(a)

        self.aprendidos: dict[str, dict] = {}
        if APRENDIDOS.exists():
            self.aprendidos = json.loads(APRENDIDOS.read_text(encoding="utf-8"))
        for chave, reg in self.aprendidos.items():
            alvo = self.por_id.get(reg["id"])
            if alvo:
                self.por_texto[chave] = alvo

    def aprender(self, nome_documento: str, autor_id: int, referencia: str) -> bool:
        """Registra "nome civil do papel -> id do SAPL" confirmado por voce.

        Retorna True se aprendeu algo novo.
        """
        chave = _normalizar(nome_documento)
        alvo = self.por_id.get(autor_id)
        if not chave or len(chave) < 6 or not alvo:
            return False
        # A correcao vale para ESTA indicacao de qualquer jeito (quem grava e
        # o correcoes.json); o que nao vale e virar alias permanente quando o
        # que o OCR leu era o timbre, e nao a assinatura.
        if not _e_nome_de_gente(chave):
            return False
        if chave in self.aprendidos and self.aprendidos[chave]["id"] == autor_id:
            return False
        self.aprendidos[chave] = {
            "id": autor_id,
            "nome": alvo["nome"],
            "confirmado_em": referencia,
        }
        self.por_texto[chave] = alvo
        return True

    def salvar_aprendidos(self) -> None:
        if not self.aprendidos:
            return
        APRENDIDOS.parent.mkdir(parents=True, exist_ok=True)
        APRENDIDOS.write_text(
            json.dumps(self.aprendidos, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )

    # ---------------------------------------------------------------- #

    def _chave_ambigua(self, chave_casada: str, consulta: str) -> bool:
        """A semelhanca veio de um alias de UMA palavra que nao identifica?

        ACIDENTE REAL, achado no lote de 2009: a indicacao 459 foi atribuida a
        "Chicao" com escore 100 e certeza alta. A assinatura no papel era
        "Francisco Gildasio de Figueiredo" - outra pessoa. O motivo: Chicao tem
        o alias "Francisco", e o fuzz.token_set_ratio devolve 100 quando os
        tokens da chave sao um SUBCONJUNTO dos da consulta. Um alias de uma
        palavra so casa, com nota maxima, com QUALQUER nome que a contenha.

        O codigo ja tratava esse risco no atalho por primeiro nome, que so
        aceita quando o nome e unico na Camara. O caminho do rapidfuzz pulava a
        conferencia - esta funcao a traz para ca.

        Apelido proprio ("Binho", "Rhalessa", "Vava") continua valendo: ele
        pertence a uma pessoa so e o teste de unicidade passa. Quem cai fora e
        o primeiro nome comum ("Francisco", "Eurico", "Rosano"), que e
        exatamente o que nao identifica ninguem sozinho.
        """
        tokens_chave = chave_casada.split()
        if len(tokens_chave) != 1:
            return False
        if len(_normalizar(consulta).split()) < 2:
            return False  # consulta tambem e de uma palavra: nada a desconfiar
        return len(self.donos_do_token.get(tokens_chave[0], set())) > 1

    def _sem_cadastro(self, reg: dict) -> dict:
        """Reconheceu QUEM assinou, mas essa pessoa nao existe como Autor.

        "Parlamentar" e "Autor" sao tabelas separadas no SAPL, e ha vereador
        antigo que so existe na primeira. Sem registro de Autor ele nao aparece
        no select do formulario, com data nenhuma - entao nao adianta procurar
        na tela.

        Este caminho existe para o programa parar de mentir. Antes, sem esses
        nomes no catalogo, a assinatura de "Katia Carvalho de Lima" virava
        "sem casamento seguro (melhor palpite Carol Pires, escore 84)" - o
        nome de outra pessoa, a cinco pontos de ser aceito sozinho. Agora diz
        de quem e a assinatura e o que falta fazer.
        """
        legs = ", ".join(reg.get("legislaturas", []))
        onde = f" [{legs}]" if legs else ""
        return self._nada(
            f"{reg['nome']} assinou, mas nao tem cadastro de Autor no SAPL{onde}"
            " - cadastre o Autor no SAPL e rode scripts\\sincronizar_autores.py"
        )

    def resolver(self, nome: str, apelido: str = "") -> dict:
        """Retorna {id, nome, origem, escore, certeza, motivo}."""
        consultas = [q for q in (apelido, nome) if q and q.strip()]
        if not consultas:
            return self._nada("nenhum nome extraido do texto")

        chave = _normalizar(" | ".join(consultas))
        self.chaves_vistas.add(chave)
        if chave in self.cache:
            achado = dict(self.cache[chave])
            achado["origem"] = "cache"
            return achado

        # 1) alias/nome exato
        for q in consultas:
            reg = self.por_texto.get(_normalizar(q))
            if reg:
                if reg.get("sem_cadastro_no_sapl"):
                    return self._sem_cadastro(reg)
                return self._guardar(chave, reg, "alias-exato", 100.0, "alta")

        # 2) semelhanca textual
        melhor_reg, melhor_escore = None, 0.0
        melhor_chave, melhor_consulta = "", ""
        chaves = list(self.por_texto)
        for q in consultas:
            achado = process.extractOne(
                _normalizar(q), chaves, scorer=fuzz.token_set_ratio
            )
            if achado and achado[1] > melhor_escore:
                melhor_escore = achado[1]
                melhor_reg = self.por_texto[achado[0]]
                melhor_chave, melhor_consulta = achado[0], q

        if melhor_reg and melhor_escore >= LIMITE_ACEITE:
            if self._chave_ambigua(melhor_chave, melhor_consulta):
                return self._nada(
                    f"semelhanca alta so por causa de '{melhor_chave}', que "
                    f"serve para mais de um vereador - confirme quem assinou"
                )
            if melhor_reg.get("sem_cadastro_no_sapl"):
                return self._sem_cadastro(melhor_reg)
            return self._guardar(
                chave, melhor_reg, "rapidfuzz", melhor_escore, "alta"
            )

        # 2b) primeiro nome, quando so um parlamentar o usa.
        # Nome repetido e raro na Camara, entao o primeiro nome quase sempre
        # basta - mas quando NAO basta ("Michael", "Professor") a ambiguidade
        # e explicita e a indicacao vai para revisao, nunca para o chute.
        for q in consultas:
            pn = _primeiro_nome(q)
            donos = self.por_primeiro_nome.get(pn, [])
            if len(donos) == 1:
                if donos[0].get("sem_cadastro_no_sapl"):
                    return self._sem_cadastro(donos[0])
                return self._guardar(
                    chave, donos[0], "primeiro-nome", melhor_escore, "alta"
                )
            if len(donos) > 1:
                nomes = ", ".join(d["nome"] for d in donos)
                return self._nada(
                    f"primeiro nome '{pn}' serve para mais de um: {nomes}"
                )

        # 3) Nao ha terceiro degrau automatico.
        #
        # O Ollama FOI testado aqui e reprovou: o qwen2.5:3b devolvia o mesmo id
        # (45, ultimo da lista) para nomes diferentes, e ainda dizia
        # "certeza: alta" - inclusive para um nome inventado que nao existe na
        # Camara. Num documento oficial isso e inaceitavel, entao o modelo
        # apenas SUGERE (ver sugerir_com_ollama) e quem decide e o glossario.
        alvo = melhor_reg["nome"] if melhor_reg else "-"
        return self._nada(
            f"sem casamento seguro (melhor palpite {alvo}, escore {melhor_escore:.0f})"
        )

    def candidatos_proximos(self, nome: str, apelido: str, quantos: int = 3) -> list[dict]:
        """Os parlamentares textualmente mais parecidos, com o escore."""
        consultas = [q for q in (apelido, nome) if q and q.strip()]
        if not consultas:
            return []
        melhores: dict[int, tuple[dict, float]] = {}
        chaves = list(self.por_texto)
        for q in consultas:
            for chave, escore, _ in process.extract(
                _normalizar(q), chaves, scorer=fuzz.token_set_ratio, limit=8
            ):
                reg = self.por_texto[chave]
                # Quem nao tem cadastro de Autor nao pode ser oferecido como
                # opcao: escolher esse nome no glossario gravaria autor_id 0,
                # que e justamente "nao resolvido". O motivo da recusa ja e
                # explicado por _sem_cadastro().
                if reg.get("sem_cadastro_no_sapl"):
                    continue
                anterior = melhores.get(reg["id"])
                if not anterior or escore > anterior[1]:
                    melhores[reg["id"]] = (reg, float(escore))
        ordenados = sorted(melhores.values(), key=lambda x: -x[1])[:quantos]
        return [{"id": r["id"], "nome": r["nome"], "escore": e} for r, e in ordenados]

    def sugerir_com_ollama(self, nome: str, apelido: str = "") -> str:
        """Pista para o glossario. NUNCA alimenta autor_id.

        Pergunta ao modelo apenas entre os 3 candidatos mais proximos - com a
        lista completa ele erra sistematicamente (ver SIS_AUTOR).
        """
        curtos = self.candidatos_proximos(nome, apelido)
        pista = "candidatos: " + ", ".join(
            f"{c['nome']} (id {c['id']}, {c['escore']:.0f})" for c in curtos
        ) if curtos else ""

        if not self.usar_ollama or not curtos:
            return pista
        try:
            r = ollama_client.escolher_autor(
                nome, apelido,
                [{"id": c["id"], "nome": c["nome"]} for c in curtos],
            )
        except ollama_client.OllamaIndisponivel:
            return pista
        if not r["id"]:
            return f"{pista} | modelo: nenhuma das opcoes"
        return f"{pista} | modelo aponta: {r['nome']} (id {r['id']}) - CONFERIR"

    # ---------------------------------------------------------------- #

    def _guardar(
        self, chave: str, reg: dict, origem: str, escore: float, certeza: str
    ) -> dict:
        item = {
            "id": reg["id"],
            "nome": reg["nome"],
            "origem": origem,
            "escore": round(float(escore), 1),
            "certeza": certeza,
            "motivo": "ok",
        }
        self.cache[chave] = item
        return item

    @staticmethod
    def _nada(motivo: str) -> dict:
        return {
            "id": 0,
            "nome": "",
            "origem": "nenhuma",
            "escore": 0.0,
            "certeza": "baixa",
            "motivo": motivo,
        }

    def salvar_cache(self) -> None:
        # Poda antes de gravar: nome que nao foi consultado nesta rodada e
        # porque a indicacao dele nao existe mais no lote atual (o PDF saiu
        # de input/). Cache sem uso so ocupa espaco e envelhece a toa - isto
        # e so performance (a resolucao refaz do zero se precisar de novo),
        # nunca corretude, entao podar e sempre seguro.
        antes = len(self.cache)
        self.cache = {k: v for k, v in self.cache.items() if k in self.chaves_vistas}
        removidas = antes - len(self.cache)
        if removidas:
            print(f"  cache_autores.json: {removidas} entrada(s) nao usada(s) removida(s)")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8"
        )
