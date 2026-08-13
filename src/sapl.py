"""Preenchimento do formulario do SAPL - a logica, sem a tela.

Este modulo nao imprime nada nem pergunta nada. Quem conversa com a pessoa e
quem chama: scripts/02_preencher_sapl.py (terminal) e gui/tela_sapl.py
(interface). Os dois preenchem exatamente do mesmo jeito porque usam as
mesmas funcoes daqui - se a regra mudar, muda para os dois de uma vez.

O que este modulo NUNCA faz, de proposito:

  - salvar a indicacao no SAPL. Ele preenche e para; conferir e salvar e
    decisao de gente.
  - digitar senha. O login e feito por voce na janela que abre, e fica
    guardado no perfil do navegador para as proximas vezes.
  - preencher a data de apresentacao e anexar o PDF. Ficaram manuais por
    decisao do orgao - a interface mostra os dois valores prontos para copiar.
"""
from __future__ import annotations

from pathlib import Path

from .config import CONFIG_DIR, RAIZ

# Perfil proprio do Playwright: guarda o cookie de sessao do SAPL para nao
# precisar logar toda vez. Esta no .gitignore - e credencial.
PERFIL = RAIZ / ".perfil_navegador"


def carregar_form() -> dict:
    import json

    return json.loads((CONFIG_DIR / "sapl_form.json").read_text(encoding="utf-8"))


def achar(pagina, candidatos: list[str]):
    """Primeiro seletor que existir de verdade na pagina."""
    for sel in candidatos:
        alvo = pagina.locator(sel)
        try:
            if alvo.count() > 0:
                return alvo.first
        except Exception:
            continue
    return None


def valor_de_select(alvo) -> str:
    """O que o campo esta mostrando AGORA. "" se nem der para ler."""
    try:
        return str(alvo.input_value())
    except Exception:
        return ""


def definir_select(pagina, alvo, valor: str) -> bool:
    """Escolhe uma opcao e CONFERE que ficou. Cai para JS quando o SAPL
    esconde o select (select2).

    A conferencia nao e zelo a toa: antes dela, o caminho do select_option
    devolvia True sem reler o campo. Quando a pagina desfazia a escolha logo
    depois, o programa dizia "preenchido" e o campo aparecia em branco na
    tela, sem um unico aviso.
    """
    valor = str(valor)
    try:
        alvo.select_option(value=valor, timeout=4000)
        if valor_de_select(alvo) == valor:
            return True
    except Exception:
        pass
    try:
        # select2 mantem o <select> nativo oculto: mexe nele e avisa a pagina.
        alvo.evaluate(
            """(el, v) => {
                el.value = v;
                el.dispatchEvent(new Event('input',  {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                if (window.jQuery) jQuery(el).trigger('change');
            }""",
            valor,
        )
    except Exception:
        return False
    return valor_de_select(alvo) == valor


def garantir_select(pagina, alvo, valor: str, tentativas: int = 3) -> bool:
    """Escolhe e insiste ate a escolha sobreviver.

    So o select "Autor" precisa disto. O SAPL o reconstroi por JavaScript toda
    vez que a data ou o tipo_autor mudam - e da para ver isso no HTML da
    pagina: os separadores sao '<option>-----</option>' SEM atributo value, e
    quem gera opcao sem value e script, nao o Django. Quando essa resposta
    chega depois da nossa escolha, ela apaga a escolha junto. Escolher, deixar
    a poeira baixar e conferir de novo resolve.
    """
    valor = str(valor)
    for _ in range(tentativas):
        definir_select(pagina, alvo, valor)
        pagina.wait_for_timeout(700)
        if valor_de_select(alvo) == valor:
            return True
    return False


def definir_texto(alvo, valor: str) -> bool:
    try:
        alvo.fill(str(valor), timeout=4000)
        return True
    except Exception:
        return False


def pagina_valida(nav, pagina):
    """Devolve uma pagina utilizavel. Se a atual foi fechada (janela fechada
    a mao, crash por ficar muito tempo em segundo plano etc.), reaproveita
    outra aba aberta no mesmo contexto ou abre uma nova - sem isso, qualquer
    fechamento acidental da janela derrubava a sessao inteira."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        if not pagina.is_closed():
            return pagina
    except PlaywrightError:
        pass
    for p in nav.pages:
        try:
            if not p.is_closed():
                return p
        except PlaywrightError:
            continue
    return nav.new_page()


def descobrir_rotas(pagina, base: str) -> list[str]:
    """Lista as rotas de materia visiveis depois do login.

    O SAPL responde 404 (nao 302) nas telas de CRUD quando o usuario nao tem
    permissao, entao so da para confirmar o caminho do formulario estando
    logado. Se o caminho do config estiver errado, isto mostra o certo.
    """
    achadas: set[str] = set()
    for caminho in ("/", "/materia/", "/sistema/"):
        try:
            pagina.goto(base + caminho, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            continue
        for href in pagina.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        ):
            if href and "materia" in href and href.startswith("/"):
                achadas.add(href.split("?")[0])
    return sorted(achadas)


def listar_campos(pagina) -> list[dict]:
    """Todos os campos reais do formulario - para descobrir os ids quando o
    SAPL de outra Camara usa nomes diferentes dos do sapl_form.json."""
    return pagina.evaluate(
        """() => [...document.querySelectorAll('input, select, textarea')].map(e => ({
              tag: e.tagName.toLowerCase(),
              tipo: e.type || '',
              id: e.id || '',
              name: e.name || '',
              rotulo: (document.querySelector(`label[for="${e.id}"]`)||{}).innerText || ''
           }))"""
    )


def preencher(pagina, form: dict, ind: dict) -> tuple[list[str], list[str]]:
    """Preenche os campos automaticos. Retorna (falhas, notas).

    falhas: problema de configuracao de verdade - vale rodar --inspecionar.
    notas: esperado, precisa de atencao manual, mas NAO e bug de config.
    """
    campos = form["campos"]
    falhas = []
    notas = []
    # O veredito do autor sai so no fim, depois da ultima conferencia: a
    # pagina ainda pode apagar a escolha depois que ela ja foi feita.
    autor_ok = True

    # "numero" fica por ULTIMO de proposito. O formulario do SAPL sugere
    # automaticamente o "proximo numero disponivel" assim que tipo_materia e
    # ano sao escolhidos - via requisicao assincrona que so volta depois do
    # nosso fill. Se numero for preenchido antes desses dois, a sugestao do
    # SAPL chega em seguida e sobrescreve o que preenchemos (foi o que
    # aconteceu: o campo sempre ficava com o ultimo numero da sequencia geral,
    # tipo 1946, em vez do numero da indicacao).
    plano = [
        ("tipo_materia", "select", ind["tipo_materia_id"]),
        ("ano", "select", ind["ano"]),
        ("regime_tramitacao", "select", ind["regime_id"]),
        ("tipo_apresentacao", "select", ind["tipo_apresentacao"]),
        # A data vem ANTES do autor de proposito: o SAPL so libera as opcoes
        # do select "Autor" depois que a data existe, porque filtra por quem
        # estava no mandato naquela data. Com a ordem invertida, o autor
        # simplesmente nunca preenchia - era o aviso "autor nao
        # pre-selecionado" que aparecia em toda indicacao.
        ("data_apresentacao", "texto", ind.get("data_apresentacao", "")),
        # A ementa vai em CAIXA ALTA para o SAPL - convencao do orgao. O
        # texto guardado em indicacoes.json/csv fica como foi extraido (para
        # servir de comparacao com o PDF original); a maiusculizacao e so
        # nesta hora, ao escrever na tela.
        ("ementa", "texto", ind["ementa"].upper()),
        ("tipo_autor", "select", ind["tipo_autor_id"]),
        ("autor", "select", ind["autor_id"]),
        ("numero", "texto", ind["numero"]),
    ]

    for nome, especie, valor in plano:
        if nome == "data_apresentacao" and not str(valor).strip():
            # Sem data nao ha o que preencher - e sem ela o autor tambem nao
            # abre. A indicacao nao devia ter chegado ate aqui: o criterio de
            # "pronto" exige data. Avisa em vez de preencher vazio.
            falhas.append(
                "data de apresentação em branco - preencha na aba de "
                "conferência (ela está no carimbo do verso)")
            continue

        if nome == "autor" and str(valor or "0").strip() == "0":
            # Autor nao resolvido. Como "pronto" exige autor, isto nao devia
            # chegar aqui - mas se chegar, nao adianta insistir tres vezes com
            # um id que nao existe: avisa e segue.
            notas.append(
                "autor não identificado no documento - escolha à mão na tela "
                "do SAPL")
            autor_ok = True  # ja avisado aqui, nao repetir no fim
            continue

        alvo = achar(pagina, campos.get(nome, []))
        if alvo is None:
            falhas.append(f"{nome}: campo nao encontrado na pagina")
            continue
        # "ano" as vezes e select, as vezes input, dependendo da versao.
        marca = alvo.evaluate("e => e.tagName.toLowerCase()")
        if marca == "select":
            # O autor e o unico select que a pagina reescreve sozinha depois
            # de escolhido - so ele precisa de insistencia.
            if nome == "autor":
                ok = garantir_select(pagina, alvo, valor)
            else:
                ok = definir_select(pagina, alvo, valor)
        else:
            ok = definir_texto(alvo, valor)
        if not ok:
            if nome == "autor":
                autor_ok = False  # o recado sai depois da ultima conferencia
            else:
                falhas.append(f"{nome}: nao aceitou o valor {valor!r}")

        # Depois de tipo_materia/ano, a sugestao automatica do SAPL pode
        # demorar um instante para chegar e reescrever o campo numero. Espera
        # aqui em vez de so no final, para o numero (preenchido por ultimo)
        # nao ser pego por uma sugestao ainda em transito.
        #
        # Depois da data e de tipo_autor, a espera e por outro motivo: os dois
        # fazem o SAPL remontar o select "Autor" (a data filtra por quem estava
        # no mandato; o tipo separa parlamentar de comissao e orgao). Escolher
        # o autor antes de a lista nova chegar nao pega: a resposta atrasada
        # apaga a escolha e o campo fica em branco. tipo_autor ficou de fora
        # desta lista por muito tempo - era essa a causa do autor em branco.
        if nome in ("tipo_materia", "ano", "data_apresentacao", "tipo_autor"):
            pagina.wait_for_timeout(1200)

    # O anexo por ultimo: e o campo mais lento (sobe arquivo) e nao influencia
    # nenhum outro. Um input de arquivo nao aceita fill() - so set_input_files.
    caminho = caminho_do_pdf(ind)
    alvo_anexo = achar(pagina, campos.get("texto_original", []))
    if alvo_anexo is None:
        notas.append("campo de anexo não encontrado - anexe o PDF à mão")
    elif not caminho.is_file():
        # Some quando voce ja anexou e apagou o arquivo: e o jeito que o
        # sistema entende "essa ja foi enviada". Nao e erro.
        notas.append(
            f"{caminho.name} não está mais em output\\pdfs - se você já "
            "cadastrou esta indicação, ignore")
    else:
        try:
            alvo_anexo.set_input_files(str(caminho), timeout=15000)
        except Exception as e:
            falhas.append(f"anexo: nao deu para anexar {caminho.name} ({e})")

    # Ultima palavra sobre o autor, ja com a pagina parada (o upload do anexo
    # acima leva alguns segundos, tempo de sobra para qualquer resposta
    # atrasada chegar). Se a escolha sumiu, escolhe de novo aqui; se nem assim
    # ficar, o recado vai para a tela em vez de o campo ficar em branco calado.
    esperado_autor = str(ind["autor_id"] or "0").strip()
    if esperado_autor != "0":
        alvo_autor = achar(pagina, campos.get("autor", []))
        if alvo_autor is None:
            autor_ok = False
        elif valor_de_select(alvo_autor) == esperado_autor:
            autor_ok = True
        else:
            autor_ok = garantir_select(pagina, alvo_autor, esperado_autor, 2)
    if not autor_ok:
        # Insistimos tres vezes e a escolha nao ficou. O que sobra e o filtro
        # do proprio SAPL: ele so oferece quem estava no mandato na data - dos
        # 32 parlamentares do catalogo, o formulario costuma listar 21. Entao
        # ou a data esta errada, ou esse vereador nao era vereador naquele dia.
        notas.append(
            f"autor não fixou: mesmo repetindo, o SAPL não manteve "
            f"{ind['autor_nome_sapl']} (id {ind['autor_id']}) — ele só oferece "
            f"quem estava no mandato em "
            f"{ind.get('data_apresentacao') or 'nesta data'}. Confira a data e "
            f"escolha à mão."
        )

    # Confere que o numero realmente ficou com o valor certo depois de tudo -
    # se algum outro evento da pagina ainda sobrescrever, isso aparece aqui em
    # vez de passar batido para a tela que o usuario confere visualmente.
    alvo_numero = achar(pagina, campos.get("numero", []))
    if alvo_numero is not None:
        atual = alvo_numero.input_value()
        if str(atual).strip() != str(ind["numero"]):
            falhas.append(
                f"numero: mostrando {atual!r} na tela, esperado {ind['numero']!r} "
                "(o SAPL deve ter sugerido outro numero depois do preenchimento - confira antes de salvar)"
            )

    return falhas, notas


def caminho_do_pdf(ind: dict) -> Path:
    """O PDF fatiado que voce anexa no campo "Texto original"."""
    from .config import PDFS_DIR

    return PDFS_DIR / f"{ind['numero']}-{ind['ano']}.pdf"
