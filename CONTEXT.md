# Concert Tracker — contexto do projeto (para retomar no Claude Code)

Peça ao Claude Code, dentro do repositório `achashow`, para ler este
arquivo e continuar a partir daqui.
Este documento resume tudo que foi decidido e descoberto numa conversa
anterior no Claude (Cowork), para não precisar repetir a pesquisa.

## O que é o projeto

Uma ferramenta pessoal que avisa quando um artista que eu ouço no Spotify
vai fazer show no Brasil (ou região escolhida), checando isso todo dia,
sozinha — sem eu precisar cadastrar manualmente cada banda nova que eu
começo a ouvir.

## Restrições que o usuário definiu

- Tem que ser **gratuita**.
- Precisa de **integração com o Spotify**.
- **Preferência por não usar IA** (IA é aceitável como camada opcional,
  desligada por padrão — ver seção "IA opcional" abaixo).
- Pode ser usada só por mim ou por mais pessoas (não é requisito, mas não
  pode fechar a porta).
- A detecção de artistas tem que ser **automática**: nada de eu lembrar
  de ir cadastrar banda nova.

## Decisões e descobertas já validadas (não precisa repesquisar)

### Spotify (regras vigentes em 2026)

- O login para ler a escuta do usuário é **obrigatório** — não existe
  endpoint público tipo "me dê os artistas do usuário X". Os dados de
  escuta só saem via OAuth do próprio usuário (`/me/...`).
- Ler o **perfil público** via scraping é proibido pelos Termos de
  Desenvolvedor da Spotify ("robot, spider... to retrieve, duplicate, or
  index any portion of the Spotify Service"). Não é um caminho usado.
- **Modo de desenvolvimento** (o único viável sem virar empresa):
  - O **dono do app** precisa ter Spotify **Premium** ativo.
  - Só até **5 usuários** autorizados por app.
  - **Modo estendido** (usuários ilimitados) exige empresa registrada,
    serviço lançado e ≥250 mil usuários ativos/mês — inviável para uso
    pessoal.
- **Refresh token expira em 6 meses** desde a autorização original
  (mudança em vigor desde 20/jul/2026). Usar o token não reseta o prazo.
  Ao expirar, a API devolve `invalid_grant` e é preciso refazer o login
  inteiro. O app já trata isso e avisa 30 dias antes.
- **Redirect URI**: `localhost` é proibido; usar loopback explícito
  `http://127.0.0.1:PORTA/callback`. HTTPS não é exigido para loopback.
- Endpoints usados, todos ainda ativos após a migração de fev/2026:
  `GET /me/top/artists` (scope `user-top-read`, `time_range` = short/
  medium/long_term), `GET /me/following` (scope `user-follow-read`,
  paginação por cursor `after`), `GET /me/player/recently-played`
  (scope `user-read-recently-played`, no máx. 50 itens, paginação por
  timestamp em ms).
- Fluxo de login: **Authorization Code + PKCE** (sem client secret).

### Alternativa sem Premium: ListenBrainz

- Alternativa validada para quem não tem Premium ou quer que outras
  pessoas usem sem cada uma precisar de um app próprio de 5 vagas.
- Cada pessoa conecta o Spotify **dentro do ListenBrainz** (uma vez;
  também expira a cada 6 meses do lado do Spotify, mas o ListenBrainz
  avisa por e-mail).
- A leitura depois é por API pública do ListenBrainz, sem token:
  `GET /1/stats/user/{user}/artists` (param `range`: month, half_yearly,
  all_time, etc.) e `GET /1/user/{user}/listens` (paginação por
  `min_ts`/`max_ts`, até 1000 por chamada).
- O código já suporta as duas fontes (`--source spotify` ou
  `--source listenbrainz`).

### Fontes de shows avaliadas

| Fonte | Veredito | Motivo |
|---|---|---|
| **JamBase** | ✅ escolhida | Plano gratuito p/ uso não comercial: 1.000 chamadas/mês. Cobre casas pequenas no Japão e já lista shows de bandas japonesas pequenas em SP. |
| Bandsintown | ❌ fora | Termos proíbem uso por fã/hobby; só artistas/equipe deles. |
| Songkick | ❌ fora | API paga por licença; declaram não aprovar projetos hobby/estudante. |
| Ticketmaster Discovery | ⚠️ testar | Grátis, 5.000 chamadas/dia, mas não confirmei se a API padrão cobre Brasil (a versão "International" não cobre e não aceita mais chaves novas). |
| Last.fm (eventos) | ❌ fora | Endpoint de eventos parece descontinuado (evidência fraca, de 2017). |
| Sympla | ❓ não avaliado | Tem API pública; não confirmei se lista eventos de terceiros ou só do organizador. |
| Busca web (Google/Bing) | ❌ fora | Sem API gratuita sustentável em 2026 (Bing aposentada, Google fechada p/ novos clientes, Brave exige cartão). |

**Casos de teste reais** (bandas japonesas pequenas com show confirmado
no Brasil, achados por fora da API, usados para validar a cobertura):
- **toe** — 18/set/2026, Cine Joia, São Paulo.
- **Mass of the Fermenting Dregs** — 22/mai/2027, Hangar 110, São Paulo
  (ingressos na 101tickets.com.br).

### JamBase — detalhes técnicos confirmados

- Base: `https://api.data.jambase.com/v3/events`
- Auth: header `Authorization: Bearer SUA_CHAVE` (+ `User-Agent` próprio).
- Parâmetros principais: `artistName` (busca por palavra-chave, pode
  trazer falsos positivos — conferir `performer[].name` no retorno),
  `geoCountryIso2` (ex.: `BR`), `eventDateFrom`/`eventDateTo`,
  `perPage` (máx. 100), `page`, `sort` (`eventDate`/`-eventDate`),
  `expandPastEvents` (default: só eventos futuros).
- Resposta: schema parecido com schema.org (`@type`: Concert/Festival,
  `startDate`, `location.address.addressLocality`, `performer[]`,
  `offers[]`, `url`).
- **Usuário já tem uma chave trial** (`jbd_trial_...`). Não está salva
  em nenhum arquivo do projeto — precisa ser exportada como variável de
  ambiente `JAMBASE_API_KEY` na hora de rodar. Conferir no painel da
  JamBase quantos dias/chamadas a trial ainda tem.

### Bloqueio conhecido: ambiente do Cowork não alcança a JamBase

A sessão anterior (Claude no Cowork, container na nuvem) tem uma
política de rede que **bloqueia** conexões diretas a
`api.data.jambase.com` (confirmado via proxy: `connect_rejected`,
"gateway answered 403 to CONNECT"). Por isso o teste de cobertura real
**ainda não foi rodado** — só testado com respostas simuladas. Isso é
uma limitação daquele ambiente específico, não deve existir no Claude
Code rodando localmente. **Primeira coisa a fazer: rodar
`jambase_coverage_test.py` de verdade e ver se a JamBase cobre os
artistas do usuário no Brasil.** Esse teste decide se o projeto se
sustenta com essa fonte ou precisa de outra camada.

### IA opcional (mantendo gratuito)

Só entra se quiser, desligada por padrão, e nunca como fonte principal:
- **Gemini API**: vários modelos Flash "sem custo"; grounding com busca
  do Google tem 5.000 consultas grátis/mês. No free tier, o conteúdo
  pode ser usado para treinar modelos do Google — por isso só mandar
  texto público (nome de artista, notícia), nunca a escuta pessoal.
- **Groq**: free tier com RPM/RPD baixos, mas suficiente para o volume
  do projeto (dezenas de chamadas/dia).
- **Cloudflare Workers AI**: 10.000 "neurons"/dia grátis.
- Uso pensado: (1) extrair data/local/artista de uma notícia que já
  passou por um filtro de palavras-chave; (2) busca web via grounding
  do Gemini para achar anúncios de shows que a JamBase não pegou.
- Faixas gratuitas de IA mudam com frequência — tratar como algo a
  reconfirmar antes de depender delas.

## O que já foi construído e testado (nesta pasta)

- **`artist_sync.py`** — detecta artistas novos sozinho, lendo Spotify
  (login PKCE) ou ListenBrainz. Primeira execução cria uma "linha de
  base" em silêncio; depois só avisa artista novo uma vez (por seguir,
  aparecer num top, ou ter ≥2 reproduções — evita alarme falso de
  playlist de terceiros). Comandos: `spotify-auth`, `sync`, `list`,
  `mute`/`unmute`. Só biblioteca padrão do Python, nada para instalar.
- **`test_artist_sync.py`** — 17 testes unitários (detecção, paginação,
  PKCE contra vetor do RFC 7636, expiração de refresh token, retry em
  429, fluxo de login completo com servidor local fake). Todos passando.
  Também rodei um teste ponta a ponta contra um servidor HTTP falso
  simulando o Spotify (login, renovação de token em 401, refresh token
  morto) — funcionou.
- **`jambase_coverage_test.py`** — script standalone para testar se a
  JamBase acha shows no Brasil para uma lista de artistas. Testado só
  com resposta simulada (mock), **nunca rodado contra a API de verdade**
  (ver bloqueio de rede acima). Lê a chave de `JAMBASE_API_KEY` (env
  var), nunca hardcoded.
- **`.gitignore`** — já ignora `data/` (onde ficam os tokens do Spotify
  salvos localmente) e `__pycache__/`.

### Resultado real do teste de cobertura (29/set/2026, rodado localmente)

Rodado no Windows local (sem o bloqueio do Cowork), com a chave trial:
- A chave funciona. JamBase tinha **372 eventos futuros no Brasil**.
- **toe** (`jambase:51211`): show do Cine Joia, SP, 18/09/2026 **está na
  base** ✅ (aparece como passado, com `expandPastEvents=true`).
- **Mass of the Fermenting Dregs** (`jambase:8977178`): 23 shows futuros
  no mundo (UK, Polônia...), mas o de **22/mai/2027 no Hangar 110 NÃO
  está na base** ❌. Buraco real de cobertura para casas pequenas no BR.
- **Coldplay** (`jambase:222008`): 0 futuros (esperado).
- Busca por `artistName` gera falsos positivos graves (ex.: "toe" casou
  com festivais inteiros por causa de um artista "Kotoe"). **Solução
  adotada:** resolver o artista em `GET /v3/artists?artistName=...`,
  pegar o de nome exato e buscar eventos por `artistId` +
  `geoCountryIso2=BR`. O campo `x-numUpcomingEvents` do artista permite
  pular a busca de eventos quando é 0 (economiza cota).

**Conclusão:** JamBase serve como fonte principal, mas 1 de 2 casos de
teste ficou de fora → vale uma segunda fonte para casas pequenas do BR
(ex.: Sympla, 101tickets, Ticketmaster BR) mais para frente.

### Ambiente local (Windows)

- Repositório: `git@github.com:bahcia-design/achashow.git` (privado),
  clonado em `C:\Users\barba\projetos\achashow`.
- Os `.py` da sessão do Cowork se perderam e foram **reescritos** aqui
  (29/set/2026): `artist_sync.py`, `jambase.py` (cliente JamBase por
  `artistId`), `jambase_coverage_test.py` e `test_artist_sync.py`
  (22 testes, todos passando: `python -m unittest`).
- Python 3.13 instalado via winget em
  `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`.

## Checklist do que falta (versão reduzida)

1. [x] Rodar o teste de cobertura da JamBase de verdade (ver resultado
   acima).
0. [x] Reescrever `artist_sync.py` + testes (perdidos) e instalar Python.
2. [ ] Rodar `artist_sync.py spotify-auth` com uma conta real e
   confirmar que artista novo é detectado no próximo `sync`.
3. [ ] Escrever o adaptador que liga `artist_sync` (lista de artistas) →
   JamBase (busca de shows) → filtro de região/data → deduplicação.
4. [ ] Orçamento de chamadas: 1.000/mês na JamBase ≈ 33/dia — decidir
   se cada artista é checado a cada N dias ou se a busca é por região
   e o cruzamento é local.
5. [ ] Canal de aviso (Telegram bot via @BotFather, ou e-mail).
6. [ ] Rotina agendada (GitHub Actions), com estado versionado no
   repositório e chaves em Secrets — nunca commitadas em texto puro.
7. [ ] Lembrete de reautorização do Spotify a cada 6 meses.

Fica para depois: feeds/crawler de blogs para bandas muito pequenas que
a JamBase não cobre, camada de IA opcional, página web, suporte a mais
de um usuário.

## Convenções do projeto (para manter consistência)

- Só biblioteca padrão do Python (sem dependências externas) até aqui —
  manter esse padrão a menos que haja um motivo forte para mudar.
- Nunca hardcodar chaves/segredos em arquivo — sempre variável de
  ambiente, e `.gitignore` cobrindo qualquer arquivo de estado/token.
- Testar com respostas simuladas (mock) antes de gastar cota de API de
  verdade.
- Comentários e mensagens de commit em português, como o resto do
  projeto até aqui.
