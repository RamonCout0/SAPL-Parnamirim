"""Abre o formulario do SAPL com os campos ja preenchidos, um por vez.

O script preenche e PARA. Ele nunca salva. Voce faz as duas coisas que ficaram
para a mao - anexar o PDF de output/pdfs/ e escrever a data de apresentacao -
confere a tela e clica em salvar.

    python scripts\\02_preencher_sapl.py --inspecionar     lista os campos reais
    python scripts\\02_preencher_sapl.py                   percorre as prontas
    python scripts\\02_preencher_sapl.py --numero 300      so a 300
    python scripts\\02_preencher_sapl.py --de 300 --ate 290

Primeira execucao: a janela abre na tela de login do SAPL e espera VOCE entrar.
A sessao fica salva no perfil do projeto, entao nas proximas vezes ja abre
logado. O script nunca digita senha - quem faz o login e voce.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

from src.config import CONFIG_DIR, OUTPUT_DIR, RAIZ

PERFIL = RAIZ / ".perfil_navegador"


def carregar_form() -> dict:
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


def definir_select(pagina, alvo, valor: str) -> bool:
    """Escolhe uma opcao. Cai para JS quando o SAPL esconde o select (select2)."""
    try:
        alvo.select_option(value=str(valor), timeout=4000)
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
            str(valor),
        )
        return alvo.input_value() == str(valor)
    except Exception:
        return False


def definir_texto(alvo, valor: str) -> bool:
    try:
        alvo.fill(str(valor), timeout=4000)
        return True
    except Exception:
        return False


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


def inspecionar(pagina) -> None:
    campos = pagina.evaluate(
        """() => [...document.querySelectorAll('input, select, textarea')].map(e => ({
              tag: e.tagName.toLowerCase(),
              tipo: e.type || '',
              id: e.id || '',
              name: e.name || '',
              rotulo: (document.querySelector(`label[for="${e.id}"]`)||{}).innerText || ''
           }))"""
    )
    print(f"\n{len(campos)} campos na pagina:\n")
    print(f"{'TAG':<9} {'TIPO':<10} {'ID':<30} {'NAME':<28} ROTULO")
    for c in campos:
        if c["tipo"] in ("hidden", "csrfmiddlewaretoken"):
            continue
        rotulo = " ".join(c["rotulo"].split())[:40]
        print(f"{c['tag']:<9} {c['tipo']:<10} {c['id']:<30} {c['name']:<28} {rotulo}")
    print("\nAjuste config\\sapl_form.json com os ids/names que aparecem acima.")


def preencher(pagina, form: dict, ind: dict) -> list[str]:
    """Preenche os campos automaticos. Retorna a lista de falhas."""
    campos = form["campos"]
    falhas = []

    plano = [
        ("tipo_materia", "select", ind["tipo_materia_id"]),
        ("ano", "select", ind["ano"]),
        ("numero", "texto", ind["numero"]),
        ("regime_tramitacao", "select", ind["regime_id"]),
        ("ementa", "texto", ind["ementa"]),
        ("tipo_autor", "select", ind["tipo_autor_id"]),
        ("autor", "select", ind["autor_id"]),
    ]

    for nome, especie, valor in plano:
        alvo = achar(pagina, campos.get(nome, []))
        if alvo is None:
            falhas.append(f"{nome}: campo nao encontrado na pagina")
            continue
        # "ano" as vezes e select, as vezes input, dependendo da versao.
        marca = alvo.evaluate("e => e.tagName.toLowerCase()")
        if marca == "select":
            ok = definir_select(pagina, alvo, valor)
        else:
            ok = definir_texto(alvo, valor)
        if not ok:
            falhas.append(f"{nome}: nao aceitou o valor {valor!r}")

    return falhas


def main() -> int:
    args = sys.argv[1:]
    form = carregar_form()
    base = form["base_url"].rstrip("/")
    url_form = base + form["caminho_formulario"]

    dados = json.loads((OUTPUT_DIR / "indicacoes.json").read_text(encoding="utf-8"))
    prontas = [i for i in dados["indicacoes"] if i["status"] == "pronto"]

    if "--numero" in args:
        alvo = int(args[args.index("--numero") + 1])
        prontas = [i for i in prontas if i["numero"] == alvo]
    if "--de" in args:
        de = int(args[args.index("--de") + 1])
        prontas = [i for i in prontas if i["numero"] <= de]
    if "--ate" in args:
        ate = int(args[args.index("--ate") + 1])
        prontas = [i for i in prontas if i["numero"] >= ate]

    so_inspecionar = "--inspecionar" in args
    if not prontas and not so_inspecionar:
        print("Nenhuma indicacao com status 'pronto'. Rode 01_extrair.py primeiro.")
        return 1

    PERFIL.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        nav = p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL),
            headless=False,
            viewport={"width": 1500, "height": 950},
            args=["--start-maximized"],
        )
        pagina = nav.pages[0] if nav.pages else nav.new_page()

        pagina.goto(url_form, wait_until="domcontentloaded")
        if "login" in pagina.url.lower():
            print(f"\nFaca o login no SAPL na janela que abriu ({pagina.url}).")
            print("Eu nao digito senha - quando terminar, aperte ENTER aqui.")
            input()
            pagina.goto(url_form, wait_until="domcontentloaded")

        if so_inspecionar:
            print(f"\nPagina: {pagina.url}\nTitulo: {pagina.title()!r}")
            inspecionar(pagina)
            print("\nRotas de materia visiveis com o seu login:")
            for rota in descobrir_rotas(pagina, base) or ["  (nenhuma encontrada)"]:
                print(f"  {rota}")
            input("\nENTER para fechar. ")
            nav.close()
            return 0

        # O formulario tem de ter o campo ementa. Se nao tiver, o caminho no
        # config esta errado (ou o usuario nao tem permissao de cadastro).
        if achar(pagina, form["campos"]["ementa"]) is None:
            print(f"\nO formulario nao apareceu em {url_form}")
            print(f"  (a pagina respondeu como: {pagina.title()!r})")
            print("\nRotas de materia visiveis com o seu login:")
            for rota in descobrir_rotas(pagina, base) or ["  (nenhuma encontrada)"]:
                print(f"  {rota}")
            print("\nAjuste 'caminho_formulario' em config\\sapl_form.json e rode de novo.")
            input("\nENTER para fechar. ")
            nav.close()
            return 1

        print(f"\n{len(prontas)} indicacoes para cadastrar.")
        print("Para cada uma: eu preencho, voce anexa o PDF, poe a data e salva.\n")

        for n, ind in enumerate(prontas, start=1):
            pagina.goto(url_form, wait_until="domcontentloaded")
            falhas = preencher(pagina, form, ind)

            print(f"{'-'*74}")
            print(f"[{n}/{len(prontas)}] Indicação {ind['numero']}/{ind['ano']}")
            print(f"  autor : {ind['autor_nome_sapl']} (id {ind['autor_id']})")
            print(f"  ementa: {ind['ementa'][:150]}...")
            print(f"  anexar: output\\pdfs\\{ind['numero']}-{ind['ano']}.pdf")
            print("  falta : data de apresentação + texto original")
            if falhas:
                print("  FALHAS AO PREENCHER:")
                for f in falhas:
                    print(f"    - {f}")
                print("    (rode --inspecionar e corrija config\\sapl_form.json)")

            resposta = input("  ENTER para a proxima, 's' para sair: ").strip().lower()
            if resposta == "s":
                break

        print("\nFim. A janela fica aberta; feche quando quiser.")
        input("ENTER para encerrar o navegador. ")
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
