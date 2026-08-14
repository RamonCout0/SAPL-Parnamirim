"""Formulario no navegador para a revisao manual - sem precisar editar CSV.

    python scripts\\03_revisar.py
    python scripts\\03_revisar.py --ano 2022    so o lote de 2022

Abre sozinho no seu navegador. Para cada indicacao pendente, mostra a pagina
escaneada ao lado de uma caixa de texto (ementa) e uma lista com o nome dos
vereadores (autor). Clicar em "Salvar e continuar" grava direto no
glossario.csv e ja mostra a proxima - sem abrir Excel, sem editar coluna
nenhuma.

Sem "--ano", pergunta qual ano revisar quando ha mais de um misturado nas
pendentes (um lote so nao incomoda com a pergunta).

Quando acabar as pendentes, ele avisa e para sozinho. Depois e so rodar
01_extrair.py de novo para essas indicacoes virarem "pronto".
"""
from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import webbrowser
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import carregar_ids
from src.pipeline import GLOSSARIO, REVISAO_DIR
# As regras de "o que falta nesta linha" e a gravacao ficam em src/revisao.py,
# compartilhadas com a interface grafica - as duas telas de revisao decidem
# igual porque e o mesmo codigo.
from src.revisao import (
    ROTULO_DE,
    falta_em,
    ja_revisada,
    linhas_do_glossario,
    precisa_de,
    salvar_correcao,
)

IMAGENS_DIR = REVISAO_DIR / "imagens"
PORTA_PREFERIDA = 8765

# Definido em main() antes de abrir o servidor - filtra a fila para um unico
# ano, quando ha mais de um misturado nas pendentes. None = mostra todos.
FILTRO_ANO: int | None = None


def ler_linhas() -> list[dict]:
    return linhas_do_glossario(GLOSSARIO)


def carregar_autores_ordenados() -> list[dict]:
    ids = carregar_ids()
    return sorted(
        (a for a in ids["autores"] if a.get("parlamentar")),
        key=lambda a: a["nome"],
    )


PAGINA = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>Revisão manual - SAPL Parnamirim</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", Arial, sans-serif;
         background: #f4f4f6; color: #222; margin: 0; padding: 0 0 60px; }}
  header {{ background: #1a2b4c; color: #fff; padding: 18px 28px; }}
  header h1 {{ margin: 0; font-size: 1.15rem; }}
  header p {{ margin: 4px 0 0; color: #b9c4dc; font-size: 0.9rem; }}
  .caixa {{ max-width: 1100px; margin: 24px auto; background: #fff;
           border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 28px; }}
  .motivo {{ background: #fff4e5; border: 1px solid #f0c36d; border-radius: 8px;
            padding: 12px 16px; margin-bottom: 20px; font-size: 0.95rem; }}
  .motivo b {{ color: #92400e; }}
  .grade {{ display: flex; gap: 28px; flex-wrap: wrap; }}
  .col-imagens {{ flex: 1 1 380px; min-width: 320px; }}
  .col-form {{ flex: 1 1 420px; min-width: 320px; }}
  .col-imagens img {{ width: 100%; border: 1px solid #ddd; border-radius: 6px;
                      margin-bottom: 12px; display: block; }}
  label {{ display: block; font-weight: 600; margin: 18px 0 6px; }}
  .referencia {{ background: #f0f2f7; border-radius: 6px; padding: 10px 12px;
                font-size: 0.88rem; color: #444; margin-bottom: 4px; white-space: pre-wrap; }}
  textarea {{ width: 100%; min-height: 130px; font-size: 1rem; font-family: inherit;
             padding: 10px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }}
  select {{ width: 100%; font-size: 1rem; padding: 9px; border: 1px solid #ccc;
           border-radius: 6px; box-sizing: border-box; background: #fff; }}
  .ajuda {{ color: #666; font-size: 0.85rem; margin-top: 4px; }}
  .botoes {{ margin-top: 26px; display: flex; gap: 12px; }}
  button {{ font-size: 1rem; padding: 12px 22px; border-radius: 8px; border: none;
           cursor: pointer; }}
  .salvar {{ background: #1a7a3c; color: #fff; font-weight: 600; }}
  .salvar:hover {{ background: #14602f; }}
  .pular {{ background: #e5e7eb; color: #333; }}
  .pular:hover {{ background: #d1d5db; }}
  .progresso {{ color: #b9c4dc; font-size: 0.85rem; }}
  .ok-tudo {{ text-align: center; padding: 60px 20px; }}
  .ok-tudo h2 {{ color: #1a7a3c; }}
  .falta {{ background: #fee2e2; border: 1px solid #fca5a5; color: #991b1b;
           border-radius: 8px; padding: 10px 16px; margin-bottom: 20px;
           font-size: 0.95rem; font-weight: 600; }}
  .resolvida {{ background: #dcfce7; border: 1px solid #86efac; color: #166534;
               border-radius: 8px; padding: 10px 16px; margin-bottom: 20px;
               font-size: 0.95rem; font-weight: 600; }}
  .navegar {{ display: flex; gap: 10px; align-items: center; margin-left: auto; }}
  .navegar a {{ color: #1a2b4c; text-decoration: none; font-size: 0.9rem;
               border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 14px; }}
  .navegar a:hover {{ background: #eef2ff; }}
</style>
</head>
<body>
<header>
  <h1>Revisão manual — Indicações do SAPL Parnamirim</h1>
  <p class="progresso">{progresso}</p>
</header>
<div class="caixa">
{conteudo}
</div>
</body>
</html>"""


def render_item(linha: dict, indice: int, fila: list[dict]) -> str:
    # "numero" e sempre o que o OCR leu (a chave da correcao); o que vale e o
    # corrigido, quando ja existe um.
    numero, ano = linha["numero"], linha["ano"]
    numero_corrigido = (linha.get("NUMERO_MANUAL") or "").strip()
    numero_mostrado = numero_corrigido or numero
    aviso_numero = (
        f"O OCR tinha lido {escape(numero)} nesta página."
        if numero_corrigido and numero_corrigido != numero
        else "Confira no papel — é este número que vai para o SAPL."
    )
    imagens_html = "".join(
        f'<img src="/imagens/{escape(nome.strip())}" alt="página da indicação">'
        for nome in (linha.get("imagens") or "").split(",")
        if nome.strip()
    )

    autores = carregar_autores_ordenados()
    autor_atual = (linha.get("AUTOR_ID_MANUAL") or "").strip()
    opcoes = ['<option value="">-- selecione o vereador --</option>']
    for a in autores:
        marcado = " selected" if autor_atual == str(a["id"]) else ""
        opcoes.append(f'<option value="{a["id"]}"{marcado}>{escape(a["nome"])}</option>')

    ementa_inicial = (linha.get("EMENTA_MANUAL") or "").strip() or (linha.get("ementa_lida_pela_maquina") or "").strip()
    autor_lido = escape(linha.get("autor_lido_pela_maquina") or "")
    sugestao_autor = escape(linha.get("sugestao_ollama_autor") or "")
    sugestao_ementa = escape(linha.get("sugestao_ollama_ementa") or "")

    referencia_bits = []
    if autor_lido:
        referencia_bits.append(f"Nome lido no papel: {autor_lido}")
    if sugestao_autor:
        referencia_bits.append(f"Pista do modelo (conferir!): {sugestao_autor}")
    referencia_autor = "\n".join(referencia_bits) or "Nenhuma pista disponível — leia a imagem."

    conteudo_extra = f'<div class="referencia">{escape(sugestao_ementa)}</div>' if sugestao_ementa else ""

    motivo = linha.get("motivo") or ""
    precisa = precisa_de(linha)
    falta = falta_em(linha)
    # Este bloco nao tem ementa/autor para corrigir: so aparece porque a
    # maquina nao consegue confirmar sozinha o numero ou o verso da folha.
    # Preencher os campos acima nao resolve; so o checkbox abaixo resolve.
    eh_estrutural = precisa == ["confirmar"]
    confirmado_atual = (linha.get("CONFIRMAR") or "").strip()
    marcado = " checked" if confirmado_atual else ""
    aviso_estrutural = (
        '<div class="motivo" style="background:#eef2ff;border-color:#a5b4fc;">'
        '<b>Este aviso não tem ementa nem autor para corrigir.</b> '
        'Confira a imagem e, se estiver tudo certo, marque a caixa abaixo.'
        '</div>'
    ) if eh_estrutural else ""

    if falta:
        situacao = (
            '<div class="falta">Ainda falta: '
            + escape(", ".join(ROTULO_DE[p] for p in falta))
            + "</div>"
        )
    else:
        situacao = (
            '<div class="resolvida">Esta indicação já está resolvida — '
            "rode a extração de novo para ela entrar na fila do SAPL.</div>"
        )

    # Navegacao livre pela fila inteira, inclusive para tras. Antes so existia
    # "a primeira pendente": nao havia como rever uma indicacao ja salva para
    # conferir ou corrigir de novo.
    anterior = f'<a href="/?i={indice - 1}">&larr; anterior</a>' if indice > 0 else ""
    proxima = (
        f'<a href="/?i={indice + 1}">próxima &rarr;</a>'
        if indice + 1 < len(fila)
        else ""
    )

    conteudo = f"""
<div class="motivo"><b>Por que está aqui:</b> {escape(motivo)}</div>
{situacao}
{aviso_estrutural}
<div class="grade">
  <div class="col-imagens">
    <label>Página escaneada</label>
    {imagens_html or '<p>(sem imagem)</p>'}
  </div>
  <div class="col-form">
    <form method="post" action="/salvar">
      <input type="hidden" name="numero" value="{escape(numero)}">
      <input type="hidden" name="ano" value="{escape(ano)}">
      <!-- As paginas dizem QUAL linha e esta quando duas foram lidas com o
           mesmo numero impresso (o lote de 2022 tem duas "706"). Sem isto, salvar
           a segunda gravava na primeira. -->
      <input type="hidden" name="paginas" value="{escape(linha.get('paginas', ''))}">
      <input type="hidden" name="i" value="{indice}">

      <label for="numero_manual">Número da indicação</label>
      <input type="text" id="numero_manual" name="numero_manual"
             value="{escape(numero_mostrado)}" inputmode="numeric"
             style="width:140px; font-size:1.1rem; padding:9px; text-align:center;
                    border:1px solid #ccc; border-radius:6px;">
      <div class="ajuda">{aviso_numero}</div>

      <label for="ementa">Ementa (confira olhando a imagem e corrija o que faltar)</label>
      <textarea id="ementa" name="ementa">{escape(ementa_inicial)}</textarea>
      <div class="ajuda">Já veio preenchida com o que a máquina leu — edite ou complete conforme o papel. Se a ementa já está correta na imagem, deixe como está.</div>
      {conteudo_extra}

      <label for="autor">Autor (vereador que assina)</label>
      <select id="autor" name="autor_id">{''.join(opcoes)}</select>
      <div class="ajuda referencia">{escape(referencia_autor)}</div>

      <label style="display:flex; align-items:center; gap:8px; font-weight:normal; margin-top:22px;">
        <input type="checkbox" name="confirmar" value="sim" style="width:18px; height:18px;"{marcado}>
        Já conferi a página: o número e as páginas estão corretos assim mesmo
      </label>
      <div class="ajuda">Marque isto quando o aviso for só sobre número deduzido ou página única — não substitui preencher ementa/autor se algum deles ainda estiver faltando.</div>

      <div class="botoes">
        <button type="submit" class="salvar">Salvar e continuar</button>
        <button type="submit" class="pular" formaction="/pular">Pular por enquanto</button>
        <div class="navegar">
          {anterior}
          {proxima}
        </div>
      </div>
    </form>
  </div>
</div>
"""
    pendentes = sum(1 for l in fila if not ja_revisada(l))
    progresso = (
        f"Indicação {numero}/{ano} — {indice + 1} de {len(fila)} "
        f"({pendentes} ainda pendente(s))"
    )
    return PAGINA.format(conteudo=conteudo, progresso=progresso)


def render_fim() -> str:
    conteudo = """
<div class="ok-tudo">
  <h2>Tudo revisado!</h2>
  <p>Agora é só voltar ao terminal e rodar o passo de extração de novo:</p>
  <p><code>.venv\\Scripts\\python scripts\\01_extrair.py</code></p>
  <p>As indicações que você acabou de revisar aqui vão virar "pronto" e entrar
  na fila do preenchimento automático. O que você escreveu fica guardado em
  <code>config\\correcoes.json</code> e vale para sempre — não se perde nas
  próximas rodadas.</p>
  <p>Pode fechar esta aba.</p>
</div>
"""
    return PAGINA.format(conteudo=conteudo, progresso="Concluído")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silencia o log de acesso no terminal

    def _html(self, corpo: str, status: int = 200) -> None:
        dados = corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _redirecionar(self, destino: str) -> None:
        self.send_response(303)
        self.send_header("Location", destino)
        self.end_headers()

    def do_GET(self):
        caminho = urlparse(self.path).path

        if caminho.startswith("/imagens/"):
            nome = unquote(caminho.removeprefix("/imagens/"))
            # So nomes de arquivo simples (o formato que nos mesmos geramos:
            # "NNN-AAAA_pgNNN.png"). Rejeitar qualquer separador de pasta
            # barra a tentativa mais obvia de escapar de IMAGENS_DIR.
            if "/" in nome or "\\" in nome or ".." in nome:
                self.send_error(404)
                return
            arquivo = IMAGENS_DIR / nome
            if not arquivo.is_file():
                self.send_error(404)
                return
            dados = arquivo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
            return

        fila = self.fila()
        if not fila:
            self._html(render_fim())
            return

        pedido = parse_qs(urlparse(self.path).query).get("i", [""])[0]
        if pedido.isdigit() and int(pedido) < len(fila):
            indice = int(pedido)
        else:
            # Sem "i" na URL: cai na primeira pendente. Se nao ha nenhuma,
            # acabou de verdade.
            indice = next(
                (i for i, l in enumerate(fila) if not ja_revisada(l)), None
            )
            if indice is None:
                self._html(render_fim())
                return

        self._html(render_item(fila[indice], indice, fila))

    def fila(self) -> list[dict]:
        """A lista INTEIRA (resolvidas tambem), na ordem do glossario.

        A fila inclui as ja resolvidas de proposito: e o que permite voltar
        numa indicacao para conferir ou corrigir o que voce mesmo escreveu.
        """
        linhas = ler_linhas()
        if FILTRO_ANO is not None:
            linhas = [l for l in linhas if l.get("ano") == str(FILTRO_ANO)]
        return linhas

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        campos = parse_qs(self.rfile.read(tamanho).decode("utf-8"))
        numero = campos.get("numero", [""])[0]
        ano = campos.get("ano", [""])[0]
        bruto = campos.get("i", [""])[0]
        indice = int(bruto) if bruto.isdigit() else 0
        caminho = urlparse(self.path).path

        if caminho == "/salvar":
            ementa = campos.get("ementa", [""])[0].strip()
            autor_id = campos.get("autor_id", [""])[0].strip()
            # Checkbox HTML so manda o campo quando marcado - a ausencia dele
            # no POST significa desmarcado, entao limpa a coluna nesse caso
            # (senao uma vez marcado ficaria marcado para sempre).
            confirmar = bool(campos.get("confirmar", [""])[0].strip())
            numero_manual = campos.get("numero_manual", [""])[0].strip()
            salvar_correcao(
                GLOSSARIO, numero, ano,
                paginas=campos.get("paginas", [""])[0].strip(),
                numero_manual=numero_manual,
                ementa=ementa, autor_id=autor_id, confirmado=confirmar,
            )

        # "Pular" era um POST para /pular que nao era tratado em lugar nenhum:
        # redirecionava para "/", que mostrava sempre a primeira pendente - a
        # MESMA de antes. O botao existia e nao pulava nada. Agora os dois
        # botoes avancam para a proxima pendente DEPOIS desta; nao havendo
        # nenhuma adiante, volta para o inicio da fila.
        self._redirecionar(self._proximo_destino(indice))

    def _proximo_destino(self, indice: int) -> str:
        fila = self.fila()
        adiante = next(
            (i for i, l in enumerate(fila) if i > indice and not ja_revisada(l)),
            None,
        )
        return f"/?i={adiante}" if adiante is not None else "/"


def escolher_porta() -> int:
    import socket
    for porta in (PORTA_PREFERIDA, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", porta))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("nao consegui abrir nenhuma porta local")


def _pedir_ano(linhas: list[dict]) -> int | None:
    """Pergunta qual ano revisar, so quando ha mais de um misturado nas
    pendentes - um lote so nao incomoda com a pergunta. Aceita "--ano AAAA"
    na linha de comando para pular a pergunta."""
    args = sys.argv[1:]
    if "--ano" in args:
        return int(args[args.index("--ano") + 1])

    pendentes = [l for l in linhas if not ja_revisada(l)]
    anos = sorted({l.get("ano") for l in pendentes if l.get("ano")}, reverse=True)
    if len(anos) <= 1:
        return None

    print("\nMais de um ano entre as pendentes:")
    for a in anos:
        qtd = sum(1 for l in pendentes if l.get("ano") == a)
        print(f"  {a}: {qtd}")
    resposta = input("Qual ano revisar? (ENTER para todos): ").strip()
    if not resposta:
        return None
    try:
        return int(resposta)
    except ValueError:
        print(f"  '{resposta}' não é um ano válido - mostrando todos.")
        return None


def main() -> int:
    global FILTRO_ANO
    linhas = ler_linhas()
    if not linhas:
        print("Nenhuma indicacao pendente de revisao. Rode 01_extrair.py primeiro.")
        return 0

    FILTRO_ANO = _pedir_ano(linhas)

    porta = escolher_porta()
    with socketserver.TCPServer(("127.0.0.1", porta), Handler) as servidor:
        url = f"http://127.0.0.1:{porta}/"
        print(f"Abrindo {url} no navegador ...")
        print("Deixe este terminal aberto enquanto revisa. Ctrl+C para parar a qualquer hora.")
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nEncerrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
