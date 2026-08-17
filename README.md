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
| **Data de apresentação** | **você**, na aba 2 — escrita à mão no carimbo, que a tela mostra ao lado do campo; daí em diante o programa a digita no SAPL |
| Texto original (anexo) | o PDF de `output/pdfs/` é anexado pelo programa |

Salvar no SAPL tem dois caminhos, e quem escolhe é você:

- **preencher e parar** (botão *Abrir o SAPL e preencher*) — o formulário abre
  preenchido e o programa espera. Você confere, salva no SAPL e clica em
  *Próxima*. É o caminho de sempre.
- **enviar automático** (botão *Enviar automático*) — você diz **quantas** e o
  programa preenche e salva sozinho, uma atrás da outra. Ele para e chama você
  em qualquer indicação com pendência, e nunca cadastra a mesma duas vezes.

---

## Instalação em outro PC

**Para quem só vai usar:** descompacte a pasta `SAPL Parnamirim` e clique duas
vezes em `SAPL Parnamirim.exe`. Não precisa de Python, nem de `.venv`, nem de
prompt de comando — o Python e as bibliotecas vão dentro do programa.

Na primeira vez, abra a aba **Instalação** e clique em *Preparar o que falta*:
ela baixa o navegador usado na etapa de envio ao SAPL (~90 MB, uma vez só).
As abas de processar e conferir funcionam sem esse download.

O programa cria `input/`, `output/` e `config/` **ao lado do executável**.
Ao atualizar para uma versão nova, copie a pasta `config/` da antiga: são as
suas correções e os nomes de vereadores já confirmados, que não precisam ser
refeitos.

### Gerar o executável (para quem mantém o projeto)

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python scripts\gerar_exe.py
```

Sai em `dist/SAPL Parnamirim/` (~170 MB), pronta para compactar e distribuir.

### Antivírus

**O Windows Defender pode bloquear o executável.** Já aconteceu aqui. Não é
problema do programa: executável gerado por PyInstaller, sem assinatura
digital e sem histórico de uso, tem o mesmo formato que um programa malicioso
empacotado — binário novo, desconhecido, que descompacta código na memória. O
que falta é reputação, não segurança.

Nunca resolva isso desligando o antivírus. As saídas legítimas, na ordem em
que funcionam melhor:

1. **Assinar o executável com certificado de código.** É a solução de
   verdade: elimina o bloqueio e vai acumulando reputação a cada versão.
   Custa uma anuidade e o certificado precisa ser emitido para a Câmara ou
   para quem publica o programa.
2. **Submeter o arquivo à Microsoft como falso positivo**, em
   [microsoft.com/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission).
   É gratuito e costuma ser resolvido em alguns dias — mas vale só para
   aquele arquivo exato, então precisa ser refeito a cada nova versão.
3. **O TI da Câmara liberar o programa na política do Defender**, como se faz
   com qualquer software interno. Vale para as máquinas do órgão.
4. **Distribuir sem empacotar:** em vez do `.exe`, uma pasta com o Python
   embutido e um atalho. O `python.exe` é assinado pela Python Software
   Foundation e não dispara a heurística de empacotador. Continua sendo dois
   cliques para o usuário; só a pasta fica menos "limpa".

### Ambiente de desenvolvimento

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

## Uso pela interface (recomendado)

Dois cliques em **`SAPL Parnamirim.bat`**. Não precisa de terminal, nem de
comando nenhum.

A janela tem três abas, na ordem do trabalho:

**1. Processar** — arraste os PDFs para a lista (ou use *Adicionar PDFs...*),
informe o **ano** e clique em **FAZER TUDO**. O andamento aparece na própria
tela: quantas páginas foram lidas, quantas indicações saíram, quantas ficaram
para conferir.

**2. Conferir** — para cada indicação que a máquina não leu com segurança, a
**página escaneada aparece do lado esquerdo** e os campos do lado direito. Em
cima, em vermelho, o que ainda falta naquela indicação ("Ainda falta: ementa,
autor"). Corrija, clique em **Salvar e continuar**, e ele vai para a próxima.
O número entre parênteses na aba diz quantas ainda faltam.

**Indicação sem autor individual.** Algumas são assinadas por todos os
vereadores — o texto diz *"Os Vereadores da Câmara Municipal de Parnamirim/RN
[...] INDICAM"* e as assinaturas ocupam páginas inteiras (caso da 439/2023).
Nessas, escolha no seletor de autor a opção **"esta indicação não tem autor
individual"**. É uma resposta, não a ausência de uma: o programa só deixa
passar sem autor quando você marca isso. Autor em branco continua segurando a
indicação — é o que impede uma assinatura mal lida de virar cadastro sem autor.

Dois botões dessa tela existem para conferir o que vai de fato para o SAPL:

- **Ver o PDF do SAPL** abre o arquivo fatiado de `output/pdfs/` — o mesmo que
  será anexado. As imagens ao lado mostram o conteúdo; só o PDF prova o que o
  SAPL vai receber.
- **Esta é continuação da anterior — juntar ↑** é a saída para quando a máquina
  partiu uma indicação em duas (uma folha de anexo lida como começo, um
  cabeçalho destruído no meio). As páginas passam para a indicação de cima e
  viram um PDF só. Fica gravado em `config/juncoes.json` e vale para sempre —
  não precisa refazer a cada rodada. Vale a partir do processamento seguinte.

**3. Enviar ao SAPL** — abre o Firefox com o formulário preenchido: número,
ano, ementa, autor, data de apresentação e o PDF anexado, tudo pelo programa.
A partir daí, dois botões:

- *Abrir o SAPL e preencher* — preenche e **para** em cada indicação. Você
  confere a tela, salva no SAPL e clica em *Próxima* aqui.
- *Enviar automático* — no campo **"Quer enviar quantas?"** você digita o
  número (ou clica em *todas*) e o programa preenche **e salva** sozinho, uma
  atrás da outra, até completar essa quantidade.

O automático não é o manual sem conferência — é o manual com a conferência
feita antes, nos dados. Cada indicação só vai sozinha se **não sobrar nenhuma
objeção**: status pronto, data, autor, ementa, PDF na pasta, nenhuma correção
sua ainda por aplicar, e nenhum recado de atenção no preenchimento da tela.
Qualquer dúvida, ela sai do automático e a tela chama você.

Duas travas que valem repetir:

- **nunca cadastra duas vezes.** O que foi salvo fica registrado em
  `output/enviados.json` e sai da fila — mesmo que você reprocesse o lote.
- **só conta como enviada o que ele confirmou na tela do SAPL.** Se a página
  não responder, se o SAPL recusar o cadastro ou se a sessão cair, ele
  responde "não cadastrou" e devolve a decisão para você. Nunca marca como
  feita uma indicação que não viu entrar.

Se você corrigiu alguma coisa na aba 2 e ainda não processou o lote de novo, a
aba 3 avisa em vermelho e **bloqueia o envio automático** — o que está na lista
ainda é o texto antigo.

### Retomar de onde você parou

A caixa **Fila de envio** manda nos dois botões, o manual e o automático.

- **Começar do número** corta a fila naquela indicação. O corte é pela posição
  na lista, não pela grandeza do número: no lote de 2023, que desce de 400 a
  301, digitar 350 tira as 400–351; no de 2022, que sobe de 601 a 710, digitar
  650 tira as 601–649. Enquanto você digita, a frase abaixo do campo diz
  exatamente o que vai acontecer (*"Vai da 350/2023 até a 301/2023 — 50
  indicação(ões), deixando 50 de fora"*).
- **Já enviei até aqui** tira essas anteriores da fila **de vez**. É para as
  que você cadastrou à mão, antes de o programa existir ou fora dele: ele não
  tem como saber delas sozinho, e sem isso elas voltavam para a fila toda
  sessão, o contador ficava errado e *todas* queria dizer "as 400 de novo".
  Elas aparecem na tabela como **"marcada por você"** — diferente de
  **"cadastrada"**, que é o que o programa fez e conferiu na tela do SAPL. Se
  errar o número, o botão *Desfazer* aparece ao lado e devolve todas para a
  fila.

## A data de apresentação: onde ela está, e por que não dá para lê-la

Duas coisas, as duas descobertas nos lotes reais:

**1. A data é de cada indicação, não do lote.** Elas chegam juntas num PDF só
porque foram digitalizadas juntas. Medido: **48 datas diferentes entre 196
indicações** de um mesmo arquivo, e 12 entre 58 de outro. Um campo único para
o lote cadastraria quase todas erradas.

**2. A data que vale é a do carimbo "Lido na Sessão", no verso — e ela é
escrita à mão.** Não é a do fecho da indicação (*"Plenário Dr. Mário
Medeiros, 16 de dezembro de 2021"*), que é quando o vereador assinou. Dos 117
carimbos encontrados nos dois lotes, o OCR entregou data legível em **zero**.
É assim que eles saem do scanner:

```
Mesa Diretora | Lido na Sessa© | Data: U ! t 3-
Mesa Dia etora | Lido na Sessao | Data: l t / c j
Mesa [3iret7ra | Lido na Sessão | • Data: 105 i~oad
```

Computador não lê letra de mão. Então o programa **não tenta adivinhar** — ele
faz o que é útil de verdade: acha a página do carimbo e **mostra essa imagem
na tela**, na hora em que você vai digitar. Você lê os garranchos ampliados e
escreve a data uma vez; ela fica guardada em `config/correcoes.json` e não
precisa ser lida de novo, nem se o lote for reprocessado.

A leitura automática continua tentando, para o caso de algum dia o carimbo vir
datilografado — mas nunca a partir da data do Plenário. Oferecer a data errada
para copiar é pior do que não oferecer nenhuma.

A interface chama exatamente o mesmo código dos scripts de terminal — os dois
caminhos produzem o mesmo resultado. Quem prefere terminal continua com os
scripts descritos abaixo.

---

## Uso pelo terminal

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
**Salvar e continuar** e ele já passa para a próxima pendente. Quando acabar,
ele avisa na tela.

No alto de cada indicação aparece **o que ainda falta** nela — "Ainda falta:
ementa, autor". Uma indicação só sai da fila quando **tudo** que ela pede está
preenchido: meia correção continua pendente, e a tela diz o que sobrou. Dá
para navegar livremente (**anterior** / **próxima**) e voltar numa indicação
já salva para conferir ou mudar o que você mesmo escreveu.

O **número** também é corrigível ali, junto com ementa e autor. Quando o OCR
destrói o cabeçalho e entrega um número que não conversa com a sequência do
lote, a indicação é barrada e a tela pede o número certo — você lê na imagem
ao lado e digita. **O PDF em `output/pdfs/` é renomeado sozinho** para o
número corrigido, já que é você quem anexa o arquivo no SAPL.

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

### Onde o seu trabalho fica guardado

Em **`config/correcoes.json`**, uma entrada por indicação, com a ementa que
você transcreveu, o id do autor que você escolheu, o número corrigido e o "já
conferi". Esse arquivo é permanente: nenhuma rodada do pipeline apaga ele, e
o que estiver ali vence qualquer dedução da máquina, para sempre.

A chave de cada entrada é o número **como o OCR leu** (`"9/2021"`, mesmo que o
certo seja 1629). Parece estranho, mas é o que faz a correção ser reencontrada
na rodada seguinte: o OCR erra igual toda vez, então é o número errado que
identifica aquela indicação de forma estável. Se a chave fosse o número
corrigido, a correção viraria órfã da indicação que corrigiu.

Pode (e vale a pena) **versionar no git**, igual ao `aliases_aprendidos.json`:
a correção que uma pessoa fez passa a valer para todo mundo que usa o
repositório.

O `output/revisao_manual/glossario.csv` **não** é a memória do sistema — é só
uma janela para as pendentes de agora, regravada a cada rodada já preenchida
com o que você digitou antes. Editar ele à mão continua funcionando: o
conteúdo é importado para o `correcoes.json` no início da rodada seguinte,
antes de qualquer regravação.

> Se você usou uma versão anterior a esta: ali o CSV *era* o único lugar das
> correções, e como ele é regravado a cada rodada, tudo que você digitava se
> perdia — a mesma indicação voltava para revisão para sempre. Na primeira
> execução desta versão, o que tiver sobrado em `glossario_anterior.csv` é
> recuperado automaticamente para o `correcoes.json`.

<details>
<summary>Prefere editar direto? (avançado)</summary>

Os mesmos dados ficam em `output/revisao_manual/`:

- `imagens/NNN-2023_pgNNN.png` — a página escaneada
- `glossario.csv` — abra num programa de planilha (Excel/LibreOffice), nunca
  num editor de código: as colunas `NUMERO_MANUAL`, `EMENTA_MANUAL`,
  `AUTOR_ID_MANUAL` e `CONFIRMAR` (as quatro que você preenche) vêm logo no
  início da linha; consulte `IDS_DE_AUTOR.md` para os ids. Escreva `sim` em
  `CONFIRMAR` para os avisos estruturais (número deduzido, 1 página) que não
  têm ementa/autor para corrigir. A coluna `precisa` diz quais **daquelas
  quatro** resolvem aquela linha específica — preencher outra não tira a
  indicação da fila. A coluna `numero` é sempre o que o OCR leu (é a chave);
  o número certo vai em `NUMERO_MANUAL`.
- `REVISAO.md` — o mesmo conteúdo, só para leitura, com as imagens já
  incorporadas (abra o preview de Markdown do editor)

`scripts/03_revisar.py` edita exatamente esse `glossario.csv` — os dois
caminhos terminam no mesmo lugar (o `config/correcoes.json`, veja acima).
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
4. **Número com separador de milhar.** A partir da indicação 1000 o papel
   escreve `Indicação n° 1.405/2022`, com ponto — e `1 405`, com espaço,
   quando o OCR troca o ponto. Os três formatos valem o mesmo número. (Até a
   correção deste ciclo, o ponto fazia o cabeçalho inteiro deixar de ser
   reconhecido: **toda** indicação de número ≥ 1000 caía em revisão manual
   com "número deduzido", e os buracos ainda atrapalhavam a dedução dos
   vizinhos.)
5. **Número lido errado.** Quando o OCR destrói o cabeçalho, ele às vezes
   entrega um número que *parece* válido. Casos reais do lote de 2021:
   `Indicacao n° /617/2021` virou 617 (era 1617) e `INDICAcAO N°. iG l9 / 2021`
   virou **9** (era 1629). Um número que não conversa com a sequência do lote
   vai obrigatoriamente para conferência, e não serve de âncora para deduzir
   os vizinhos. (Antes disso, o "9" tinha ementa e autor bons e foi
   classificado como **pronto** — iria para o SAPL como *Indicação 9/2021*.
   E ainda fez a indicação seguinte ser deduzida como "10" em vez de 1630.)

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
- número lido do papel (não deduzido) **e coerente com a sequência do lote**
- bloco com 2 páginas ou mais

Ementa que **você** transcreveu não passa pelo critério de tamanho nem pelo de
confiança: o critério existe para desconfiar do OCR, e ali não há OCR. Sem
essa exceção, uma ementa curta legítima ("INDICA A PODA DE ÁRVORE NA RUA X")
ficaria pedindo revisão para sempre, mesmo depois de transcrita certinho.

Qualquer coisa fora disso vira revisão manual.

## Estrutura

```
SAPL Parnamirim.bat        abre a interface com dois cliques
gui/
  app.py         a janela e as tres abas
  tela_inicio.py PDFs + ano + data + o botao "Fazer tudo"
  tela_revisao.py página escaneada ao lado dos campos
  tela_sapl.py   envio ao SAPL, uma indicação por vez
  sapl_worker.py a sessão do Firefox rodando em segundo plano
  tarefas.py     roda o pipeline sem congelar a janela
  estado.py      ano e data lembrados entre sessões
  visual.py      cores e fontes
config/
  sapl_ids.json            ids dos selects + aliases dos autores
  sapl_form.json           seletores dos campos do formulário
  aliases_aprendidos.json  nomes civis que você confirmou (cresce com o uso)
  correcoes.json           ementa/autor/"já conferi" que você corrigiu — permanente
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
src/
  datas.py       acha a página do carimbo "Lido na Sessão" (a data é manuscrita)
  ambiente.py    confere e prepara o que falta na máquina
  sapl.py        preenchimento do formulário (usado pela interface e pelo script)
scripts/
  interface.py          abre a interface gráfica
  00_diagnostico.py     confere o fatiamento
  01_extrair.py         pipeline completo
  02_preencher_sapl.py  abre o formulário preenchido
  03_revisar.py         formulário no navegador para a revisão manual
  instalar.ps1          prepara o ambiente numa máquina nova
  ver_pagina.py         depuração: texto cru vs limpo de uma página
tests/
  test_detect.py        leitura do número no cabeçalho (inclusive "1.405/2022")
  test_ciclo_revisao.py a correção manual sobrevive às rodadas seguintes
```

## Testes

```bash
.venv\Scripts\python -m unittest discover -s tests
```

Não precisa de PDF nem de rede: são as regras de detecção e o ciclo de
revisão, que é onde um ajuste inocente quebra outra coisa em silêncio. Rode
antes de commitar qualquer mudança em `src/detect.py`, `src/pipeline.py` ou
`src/revisao.py`.

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
