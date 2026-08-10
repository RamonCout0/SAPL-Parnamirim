# Automação de indicações — SAPL Parnamirim

Pega um PDF escaneado com **muitas indicações juntas**, separa uma por uma,
extrai os campos e abre o formulário do SAPL já preenchido.

Roda 100% local: o OCR já vem embutido no PDF e o modelo de linguagem é o
**Ollama** na própria máquina. Nada sai do computador.

**Requisitos reais:** Python 3.9 ou superior. Nada mais é obrigatório —
sem GPU, sem Ollama, sem internet para processar. O Ollama é opcional e
`--sem-ollama` produz o mesmo conjunto de indicações prontas (testado: 91/9 nos
dois casos). Internet só é necessária no passo 4, para acessar o SAPL.

---

## O que é automático e o que é seu

| Campo do SAPL | Como é preenchido |
|---|---|
| Tipo de matéria | fixo: **Indicação** (id 6) |
| Ano | fixo por lote: **2023** |
| Número | lido do cabeçalho de cada indicação |
| Tipo de autor | fixo: **Parlamentar** (id 2) |
| Autor | nome do papel → id do SAPL (alias + rapidfuzz + glossário) |
| Regime de tramitação | fixo: **Ordinária** (id 1) |
| Ementa | texto após INDICA / REITERA / RETIRA / VEM INDICAR, até "Justificativa" |
| **Data de apresentação** | **você** |
| **Texto original (anexo)** | **você** — o PDF já sai pronto em `output/pdfs/` |

O script de navegador **preenche e para**. Ele nunca salva: você confere a tela,
anexa o PDF, escreve a data e clica em salvar.

---

## Instalação em outro PC

```powershell
git clone <url-do-repositorio>
cd SAPL-Parnamirim
powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
```

O instalador cria o `.venv`, instala as bibliotecas, baixa o Chromium do
Playwright e, se o Ollama estiver presente, o modelo. Se faltar Python, ele
instala o 3.12 via `winget`. Ele aborta com mensagem clara em qualquer falha —
não continua com o ambiente meio pronto.

**Use um caminho curto.** O Windows limita caminhos a 260 caracteres e o
`pypdfium2` cria arquivos bem fundo dentro do `.venv`; num caminho longo o
`pip install` falha. `C:\SAPL-Parnamirim` ou `Documentos\SAPL-Parnamirim` está
ótimo. O instalador confere isso antes de começar.

Três coisas **não** vêm no repositório e são recriadas em cada máquina:
`.venv/` (guarda caminhos absolutos, copiar não funciona), o navegador do
Playwright, e o modelo do Ollama. O login do SAPL também é por máquina — cada
pessoa entra com o próprio usuário na primeira execução do passo 4.

Em Linux ou macOS o código funciona igual (nada de específico do Windows), mas
o `instalar.ps1` é PowerShell; lá basta:
`python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium`.

---

## Uso

### 1. Conferir o fatiamento

```bash
.venv\Scripts\python scripts\00_diagnostico.py "%USERPROFILE%\Downloads\SEU_ARQUIVO.pdf" 2023
```

Mostra quantas indicações achou, a faixa de páginas de cada uma e o que ficou
duvidoso. Rode sempre que trocar o PDF de entrada.

### 2. Extrair

```bash
.venv\Scripts\python scripts\01_extrair.py "%USERPROFILE%\Downloads\SEU_ARQUIVO.pdf"
```

Gera em `output/`:

```
pdfs/NNN-2023.pdf        um PDF por indicação, pronto para anexar
indicacoes.csv           uma linha por indicação, com os ids do SAPL
indicacoes.json          o mesmo, com toda a rastreabilidade
markdown/NNN-2023.md     leitura humana de cada indicação
revisao_manual/          o que não deu para ler com segurança
```

Opções: `--sem-ollama` (rápido, só regex) · `--sem-pdfs` · `--ano 2024`

### 3. Resolver a revisão manual

As indicações que não passaram no critério de confiança **não vão para o SAPL**.
Elas aparecem em `output/revisao_manual/`:

- `imagens/NNN-2023_pgNNN.png` — a página escaneada, legível na tela
- `glossario.csv` — abra no Excel e preencha só as colunas em MAIÚSCULO:
  - `EMENTA_MANUAL` — transcreva olhando o PNG
  - `AUTOR_ID_MANUAL` — o id, consultando `IDS_DE_AUTOR.md`
- as outras colunas são informativas: o que a máquina leu, os candidatos mais
  próximos e o palpite do modelo

Depois **rode o passo 2 de novo**. O que você escreveu vence qualquer dedução
da máquina, e cada nome civil que você confirmar entra em
`config/aliases_aprendidos.json` — na próxima vez ele resolve sozinho.

Esse arquivo **é versionado**: dando commit nele, o mapeamento
"nome civil → nome político" passa a valer para todo mundo que usa o
repositório. O glossário só precisa ser descoberto uma vez, por uma pessoa.
Um único nome pode valer muitas indicações — *Hamilton Rademacker Pereira →
Binho de Ambrósio* resolveu 8 de uma vez neste lote.

### 4. Preencher o SAPL

```bash
.venv\Scripts\python scripts\02_preencher_sapl.py
```

Na primeira vez a janela abre no login do SAPL e espera você entrar; a sessão
fica salva em `.perfil_navegador/`. O script nunca digita senha.

Se algum campo não for encontrado, descubra os ids reais da página:

```bash
.venv\Scripts\python scripts\02_preencher_sapl.py --inspecionar
```

e ajuste `config/sapl_form.json`.

Outros modos: `--numero 300` · `--de 300 --ate 290`

---

## Como a separação funciona

A indicação N começa na página do seu cabeçalho e termina **na página anterior
ao começo da próxima**. Nunca por contagem fixa de páginas — é isso que faz os
casos especiais se resolverem sozinhos: se a 101 tem uma página extra de fotos,
o bloco dela vai de 1 a 3 porque a 102 só começa na 4.

Três armadilhas reais do documento, todas tratadas:

1. **Número citado no corpo de outra indicação.** "REITERA a indicação n°
   498/2022" não abre bloco novo — vale só o primeiro cabeçalho da página.
2. **Página de anexo.** "Anexo à Indicação n° 233/2023. Registro fotográfico"
   repete o número; é continuação, não início.
3. **Cabeçalho ilegível.** Quando o OCR perde a linha do número (aconteceu com
   a 295), a página ainda é reconhecida pela fórmula de abertura
   "vereador com assento nesta egrégia Casa Legislativa", e o número é deduzido
   pela posição na sequência — sempre marcado para você confirmar.

## Onde o Ollama entra (e onde não entra)

O modelo **não decide nada que vá para o SAPL**. Isso foi uma decisão tomada
depois de medir: com a lista dos 32 parlamentares inteira, o `qwen2.5:3b`
devolvia sempre o mesmo id (o último) com "certeza alta", inclusive para um nome
inventado. E ao "corrigir" ementas, chegou a trocar *Rosano Taveira da Cunha*
por *Rosano Taveiraara Cunha*.

Então o desenho é:

- **Decide:** regex + tabela de aliases + rapidfuzz + primeiro nome único +
  o seu glossário. Tudo determinístico e auditável.
- **Sugere:** o Ollama, restrito a escolher entre os **3 candidatos mais
  próximos** — nessa forma ele acerta OCR corrompido ("EdéV Rodrigues Queiroz"
  → Eder Queiroz) e recusa o que não dá para saber. A resposta vai para uma
  coluna do glossário marcada `CONFERIR`, nunca para o formulário.

A ementa que vai para o SAPL é sempre o **texto literal do OCR** ou o que você
transcreveu — nunca uma reescrita do modelo.

## Critério para uma indicação ir sozinha

Tudo tem de valer:

- ementa entre 40 e 900 caracteres, com confiança ≥ 0,6
- autor resolvido por alias, rapidfuzz ≥ 88 ou primeiro nome único
- número lido do papel (não deduzido)
- bloco com 2 páginas ou mais

Qualquer coisa fora disso vira revisão manual.

## Estrutura

```
config/
  sapl_ids.json            ids dos selects + aliases dos autores
  sapl_form.json           seletores dos campos do formulário
  aliases_aprendidos.json  nomes civis que você confirmou (cresce com o uso)
src/
  textlayer.py   PDF -> texto por página, limpando timbre e carimbo
  detect.py      acha os inícios e fatia em blocos
  campos.py      ementa e nome do autor por regex
  autores.py     nome do papel -> id do SAPL
  ollama_client.py
  revisao.py     PNG das páginas duvidosas + glossário
  pipeline.py    orquestra tudo
scripts/
  00_diagnostico.py     confere o fatiamento
  01_extrair.py         pipeline completo
  02_preencher_sapl.py  abre o formulário preenchido
  ver_pagina.py         depuração: texto cru vs limpo de uma página
```

## Ambiente

Python 3.12 em `.venv`, Ollama com `qwen2.5:3b-instruct`, Playwright + Chromium.

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```


Créditos ao Rafael Veritas Por colaborar no projeto.
