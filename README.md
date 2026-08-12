# Automação de indicações — SAPL Parnamirim

Pega um PDF escaneado com **muitas indicações juntas**, separa uma por uma,
extrai os campos e abre o formulário do SAPL já preenchido.

Roda 100% local: o modelo de linguagem é o **Ollama** na própria máquina.
Nada sai do computador.

**Requisitos reais:** Python 3.9 ou superior. Nada mais é obrigatório —
sem GPU, sem Ollama, sem Tesseract, sem internet para processar. O Ollama é
opcional e `--sem-ollama` produz o mesmo conjunto de indicações prontas
(testado: mesmo resultado nos dois casos). Internet só é necessária no passo
5, para acessar o SAPL.

A maioria dos lotes já vem com OCR embutido no PDF (o padrão que a Câmara
usa). Para as páginas que **não** vêm - scans crus, sem camada de texto
nenhuma - o Tesseract entra como reserva automática, rodando OCR local só
naquela página. Sem o Tesseract instalado, essas páginas raras vão direto
para revisão manual em vez de travar o processamento.

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
| Tipo de apresentação | fixo: **Escrita** ("E") |
| Ementa | texto após INDICA / REITERA / RETIRA / VEM INDICAR, até "Justificativa" — preenchida **EM CAIXA ALTA** |
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

O instalador cria o `.venv`, instala as bibliotecas, baixa o Firefox do
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
`python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install firefox`.

---

## Uso

### 1. Colocar os PDFs em `input/`

Copie os lotes de indicações para dentro de `input/`. Pode colocar mais de um
de uma vez. Se o nome do arquivo terminar em `@AAAA.pdf` (o padrão que você já
usa, tipo `..._300_A_201@2023.pdf`), o ano daquele lote é lido do próprio
nome; senão vale o `--ano` do comando (2023 por padrão).

### 2. Conferir o fatiamento (opcional, mas recomendado no primeiro lote)

```bash
.venv\Scripts\python scripts\00_diagnostico.py "input\SEU_ARQUIVO.pdf" 2023
```

Mostra quantas indicações achou, a faixa de páginas de cada uma e o que ficou
duvidoso — antes de gerar qualquer coisa.

### 3. Extrair

```bash
.venv\Scripts\python scripts\01_extrair.py
```

Sem argumento nenhum: processa **tudo** que estiver em `input/`. **A cada
execução, `output/` é atualizado a partir do que estiver em `input/` naquele
momento** — se você tirar um PDF de lá, as indicações dele somem do output na
rodada seguinte. As correções que você já fez no glossário não se perdem:
isso é preservado entre execuções.

`output/pdfs/` tem uma regra especial: **se você apagou o PDF de uma
indicação depois de anexá-la no SAPL, ele não volta.** O sistema guarda um
registro (`output/pdfs_gerados.json`) de tudo que já foi fatiado alguma vez;
se o arquivo sumiu mas o registro mostra que ele já existiu, entende como "já
processei essa" e não recria. Só é gerado de novo um PDF genuinamente novo
(indicação que nunca teve arquivo). Quando a indicação inteira some de
`input/` (você tirou o PDF de origem), o arquivo órfão é sempre removido,
apagado por você ou não — apagar o PDF de uma indicação vira, na prática, o
seu jeito de marcar "já enviei ao SAPL".

`output/cache_autores.json` (nomes já resolvidos, para não recalcular toda
hora) se ajusta sozinho do mesmo jeito: a cada rodada, uma entrada que não
pertence a nenhuma indicação do lote atual é removida — assim ele nunca fica
pesado com nomes de PDFs que já saíram de `input/`. Isso é só performance,
nunca corretude: se um PDF voltar depois, o nome é resolvido de novo do zero,
sem risco de erro. Diferente do `aliases_aprendidos.json`, que é para
sempre.

Gera em `output/`:

```
pdfs/NNN-2023.pdf        um PDF por indicação, pronto para anexar
indicacoes.csv           uma linha por indicação, com os ids do SAPL
indicacoes.json          o mesmo, com toda a rastreabilidade
markdown/NNN-2023.md     leitura humana de cada indicação
revisao_manual/          o que não deu para ler com segurança
```

Opções: `--sem-ollama` (rápido, só regex) · `--sem-pdfs` · `--ano 2024` ·
passar o caminho de um único PDF em vez de usar `input/` (para testar um
arquivo isolado, sem mexer nos outros)

### 4. Resolver a revisão manual

As indicações que não passaram no critério de confiança **não vão para o SAPL**.
Para resolver, abra um formulário no navegador — não precisa editar planilha
nem CSV:

```bash
.venv\Scripts\python scripts\03_revisar.py
```

Abre sozinho no navegador. Para cada indicação pendente, mostra a página
escaneada ao lado de uma caixa de texto (já vem com o que a máquina leu, só
corrija o que faltar) e uma lista com o nome dos vereadores. Clique em
**Salvar e continuar** e ele já passa para a próxima. Quando acabar, ele avisa
na tela.

**Nem todo aviso é sobre ementa ou autor.** "Número deduzido pela sequência"
e "bloco com 1 página" são avisos estruturais — não têm texto para corrigir,
só pedem que você confira a imagem. Para esses, o formulário mostra uma caixa
"Já conferi a página" — marque e salve, sem precisar mexer em ementa/autor.
Sem isso marcado, a indicação ficaria pedindo revisão para sempre, mesmo
depois de você preencher ementa e autor certinhos, porque o motivo que estava
bloqueando era outro.

Depois **rode o passo 3 de novo**. O que você escreveu vence qualquer dedução
da máquina, e cada nome civil que você confirmar entra em
`config/aliases_aprendidos.json` — na próxima vez ele resolve sozinho.

<details>
<summary>Prefere editar direto? (avançado)</summary>

Os mesmos dados ficam em `output/revisao_manual/`:

- `imagens/NNN-2023_pgNNN.png` — a página escaneada
- `glossario.csv` — abra num programa de planilha (Excel/LibreOffice), nunca
  num editor de código: as colunas `EMENTA_MANUAL`, `AUTOR_ID_MANUAL` e
  `CONFIRMAR` (as três que você preenche) vêm logo no início da linha;
  consulte `IDS_DE_AUTOR.md` para os ids. Escreva `sim` em `CONFIRMAR` para
  os avisos estruturais (número deduzido, 1 página) que não têm ementa/autor
  para corrigir.
- `REVISAO.md` — o mesmo conteúdo, só para leitura, com as imagens já
  incorporadas (abra o preview de Markdown do editor)

`scripts/03_revisar.py` edita exatamente esse `glossario.csv` — os dois
caminhos terminam no mesmo lugar.

Um `glossario_anterior.csv` pode aparecer ao lado: é só uma cópia de
segurança automática, feita sempre que o glossário é reescrito com correções
suas já dentro — o sistema nunca volta a ler esse arquivo, é só para você
recuperar algo manualmente se precisar. Pode apagar sem medo.
</details>

Esse arquivo **é versionado**: dando commit nele, o mapeamento
"nome civil → nome político" passa a valer para todo mundo que usa o
repositório. O glossário só precisa ser descoberto uma vez, por uma pessoa.
Um único nome pode valer muitas indicações — *Hamilton Rademacker Pereira →
Binho de Ambrósio* resolveu 8 de uma vez neste lote.

### 5. Preencher o SAPL

```bash
.venv\Scripts\python scripts\02_preencher_sapl.py
```

Abre uma janela de **Firefox** — uma instância própria do Playwright, não o
Firefox do seu dia a dia (não tem como conectar na janela que você já tem
aberta: isso só funciona com navegadores baseados em Chrome). Na primeira vez
a janela abre no login do SAPL e espera você entrar; a sessão fica salva em
`.perfil_navegador/`, então nas próximas já abre logado. O script nunca digita
senha.

Se algum campo não for encontrado, descubra os ids reais da página:

```bash
.venv\Scripts\python scripts\02_preencher_sapl.py --inspecionar
```

e ajuste `config/sapl_form.json`.

Outros modos: `--numero 300` · `--de 300 --ate 290` · `--ano 2022`. Sem
nenhum desses, o script pergunta o ano (só quando há mais de um misturado) e
de qual número começar — útil para retomar de onde parou sem apertar ENTER
em tudo de novo.

**O campo "Autor" costuma não aceitar valor antes da data.** O SAPL só libera
as opções desse select depois que a data de apresentação é preenchida (filtra
pelo mandato vigente naquela data) — como a data é sempre manual, isso
aparece como `atenção: autor não pré-selecionado`, já dizendo qual autor
escolher à mão. Não é falha de configuração; não precisa rodar
`--inspecionar` por causa disso.

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

## Página sem OCR nenhum

Todo PDF passa por essa checagem, página por página. Se o texto embutido no
PDF está vazio (ou quase — scans crus, sem qualquer camada de texto), o
Tesseract entra automaticamente e faz o OCR **só daquela página**, localmente.
O texto que ele produz segue para o **mesmo** critério de confiança de
sempre (extração de ementa, autor, tamanho mínimo) — não existe regra
especial para texto vindo de OCR local: se não passar, vai para revisão
manual, exatamente como qualquer outra página problemática.

Sem o Tesseract instalado, essas páginas simplesmente ficam sem texto e vão
para revisão — o processamento continua normalmente para o resto do lote.

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
  ocr.py         OCR de reserva (Tesseract) para página sem texto embutido
  progresso.py   barra de progresso no terminal
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
  03_revisar.py         formulário no navegador para a revisão manual
  instalar.ps1          prepara o ambiente numa máquina nova
  ver_pagina.py         depuração: texto cru vs limpo de uma página
```

## Ambiente

Python 3.12 em `.venv`, Ollama com `qwen2.5:3b-instruct`, Playwright + Firefox,
Tesseract OCR + pacote de português (opcional — ver
[Página sem OCR nenhum](#página-sem-ocr-nenhum)).

`scripts\instalar.ps1` cuida de tudo isso automaticamente. Para só as
bibliotecas Python:

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```


Créditos ao Rafael Veritas Por colaborar no projeto.
