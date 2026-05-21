# Tallent Intelligence CRM — Dashboard

Dashboard SPA single-file para o CRM autônomo de recrutamento SOREN. Lê do Notion ao vivo (sem banco intermediário) e roda em Vercel como funções serverless Python.

- **Produção:** https://rtx-dashboard-chi.vercel.app
- **Deploy:** `vercel --prod` (CLI Vercel, sem pipeline Git/GitHub)
- **Origem dos dados:** Notion API (5 bases — ver [Backends](#backends))
- **Stack:** HTML/CSS/JS inline + Python serverless (Vercel `@vercel/python`)

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│  index.html (SPA single-file)                                │
│  ├── Sidebar / topbar / router showView()                    │
│  ├── Dashboard (KPIs)                                        │
│  ├── Empresas-alvo (tabela + edição inline)                  │
│  ├── Talentos (tabela com filtros)                           │
│  ├── Pipeline (Kanban interativo drag-drop)                  │
│  ├── Modal de histórico (popup por card)                     │
│  └── Chat AI (FAB)                                           │
└──────────────────────────────────────────────────────────────┘
                          ▼ (fetch /api/...)
┌──────────────────────────────────────────────────────────────┐
│  Funções serverless Python (api/)                            │
│  ├── data.py            métricas agregadas                   │
│  ├── insights.py        Claude gera 4 insights acionáveis    │
│  ├── chat.py            Claude responde perguntas livres     │
│  ├── empresas.py        lista empresas-alvo                  │
│  ├── update_empresa.py  PATCH prioridade empresa             │
│  ├── talentos.py        lista talentos                       │
│  ├── update_talento.py  PATCH status/notas/motivo            │
│  └── interacoes.py      histórico LinkedIn+Email por candidato│
└──────────────────────────────────────────────────────────────┘
                          ▼ (Notion REST API)
┌──────────────────────────────────────────────────────────────┐
│  Notion (source of truth)                                    │
│  ├── DB_TALENTOS   35de2f848c81804eba5ddedff68f6cc7          │
│  ├── DB_LINKEDIN   0de0fd3843f44df2932314b2f43c4ff4          │
│  ├── DB_EMAIL      bee299209e5143dbbc7a7a68d0d6626d          │
│  └── DB_EMPRESAS   1ef48cef7ef2413fa81a6a87438e89e3          │
└──────────────────────────────────────────────────────────────┘
```

## Estrutura do repositório

```
/
├── index.html              SPA inteira (HTML + CSS + JS inline)
├── api/                    Funções serverless Python
│   ├── data.py
│   ├── insights.py
│   ├── chat.py
│   ├── empresas.py
│   ├── update_empresa.py
│   ├── talentos.py
│   ├── update_talento.py
│   └── interacoes.py
├── assets/                 logos / imagens estáticas
│   └── rtx.png
├── vercel.json             builds + routes
├── requirements.txt        anthropic>=0.40.0
└── .claude/settings.json   hook Stop: vercel --prod no fim da sessão
```

---

## Backends

### Notion (camada de dados)

| Database | ID | Usado em |
|---|---|---|
| Talentos | `35de2f848c81804eba5ddedff68f6cc7` | `data.py`, `talentos.py`, `update_talento.py`, `interacoes.py` (lookup nome via page_id) |
| Interação LinkedIn | `0de0fd3843f44df2932314b2f43c4ff4` | `data.py`, `interacoes.py` |
| Interação E-mail | `bee299209e5143dbbc7a7a68d0d6626d` | `data.py`, `interacoes.py` |
| Empresas-alvo | `1ef48cef7ef2413fa81a6a87438e89e3` | `empresas.py`, `update_empresa.py` |

Auth via `NOTION_TOKEN` (env var). Versão API: `Notion-Version: 2022-06-28`.

### Anthropic (Claude)

- `insights.py` — Sonnet 4.6 com prompt caching (cache_control ephemeral) gera 4 insights JSON
- `chat.py` — Sonnet 4.6 conversational
- Auth via `ANTHROPIC_API_KEY`
- Fallback heurístico em `insights.py` quando key ausente

---

## Endpoints HTTP

| Endpoint | Método | Descrição | Cache |
|---|---|---|---|
| `/api/data` | GET | KPIs gerais + pipeline + classificação | — |
| `/api/insights` | GET | 4 insights gerados pelo Claude | 10 min (server) |
| `/api/chat` | POST | Chat livre com Claude | — |
| `/api/empresas` | GET | Lista empresas-alvo. `?fresh=1` ignora cache | 3 min (server) |
| `/api/update_empresa` | POST | PATCH prioridade empresa. Body: `{page_id, prioridade}` | — |
| `/api/talentos` | GET | Lista talentos. `?fresh=1` ignora cache | 3 min (server) |
| `/api/update_talento` | POST | PATCH talento. Body: `{page_id, status?, motivo_descarte?, observacoes?, proxima_acao?}` | — |
| `/api/interacoes` | GET | Histórico de um candidato. `?nome=` (preferido) ou `?page_id=` | — |

### Padrão de cache

Endpoints de listagem (`empresas`, `talentos`) usam in-memory cache (`CACHE_TTL = 180s`) por instance de função.

- Como Vercel cria instâncias separadas para cada função, **invalidar o cache de um endpoint via outro endpoint é impossível**.
- Solução: o frontend mantém `let _dirty = false` no IIFE do Kanban. Quando um PATCH é bem-sucedido (ex.: arrasta card), `_dirty = true`. Próximo refresh adiciona `?fresh=1`. Botão Refresh manual também passa `?fresh=1`.

---

## Pipeline (Kanban interativo)

### Estrutura de colunas (STAGES)

| Ordem | id | Título | accent | Statuses do Notion contidos | primary (drop target) |
|---|---|---|---|---|---|
| 1 | `prospect` | Prospecção | `#6e7178` | `Mapeado`, `Qualificado` | `Mapeado` |
| 2 | `approved` | Aprovado | `#479dec` | `Aprovado para contato` | `Aprovado para contato` |
| 3 | `contact` | Contato | `#22d3ee` | `Contato enviado`, `Conexão aceita` | `Contato enviado` |
| 4 | `engage` | Engajamento | `#ecCF06` | `Aguardando resposta`, `Respondeu` | `Aguardando resposta` |
| 5 | `close` | Fechamento | `#a8ff53` | `Reunião marcada`, `Entrevistado`, `Aprovado` | `Reunião marcada` |
| 6 | `hired` | Contratado | `#10b981` | `Contratado` | `Contratado` |
| 7 | `lost` | Descartado | `#f43f5e` | `Descartado`, `Não retornou`, `Sem interesse`, `Não aceitou`, `Nutrição futura` | `Descartado` |

### Regras de fluxo

- **Após agendamento confirmado** (`Reunião marcada`) → entra na coluna `Fechamento`
- **Após reunião** → operador arrasta manualmente para `Contratado` ou `Descartado` conforme decisão
- **Drag-and-drop** chama `/api/update_talento` com `status = STAGE.primary`. Optimistic UI + rollback em erro
- **Refresh manual**: botão no header do Kanban força `?fresh=1`

### Modal de histórico (`📋` no card)

- Acionado pelo ícone SVG relógio+documento ao lado do `↗` LinkedIn no card
- Busca em `/api/interacoes?nome=<nome>&page_id=<id>`
- **Vinculação com DB_EMAIL/DB_LINKEDIN**: feita por campo `Candidato` (rich_text) — NÃO por relation. Estratégia em cascata: `equals` → `contains` nome completo → `contains` primeiro+último nome
- Mostra timeline cronológica (mais recente primeiro) com canal/tipo/status/data/mensagem/resposta
- **Editor de notas no rodapé**: textarea editável que salva em `DB_TALENTOS.Motivo de descarte` (quando candidato está em status de descarte) ou `DB_TALENTOS.Observações` (demais casos)
- Fechamento: ✕, clique fora, ou Escape

---

## Design System

Tema **"Midnight Terminal"** com CSS custom properties.

- Fontes: **Outfit** (display), **Inter** (body), **JetBrains Mono** (data/números)
- Paleta chave: `--color-spring-green: #a8ff53`, `--color-obsidian-black: #121317`, `--color-charcoal-raised: #1a1c22`, `--color-midnight-surface: #232529`, `--color-ash-gray: #3a3d44`, `--color-cloud-gray: #9da3ad`, `--color-whisper-white: #f1f3f5`
- Acentos por coluna do Kanban: definidos no array `STAGES` e injetados via `--col-accent` inline em cada card

---

## Regras de código (críticas)

| Regra | Razão |
|---|---|
| **NUNCA usar `innerHTML` para dados dinâmicos** | Hook de segurança bloqueia. Usar `createElement` / `replaceChildren` / `textContent` / `document.createTextNode` |
| **`<svg>` estático pode ir em `innerHTML`** | Aceitável quando o conteúdo é literal e não vem de user/API |
| **Elementos flutuantes (dropdowns, modais)** | Devem ficar fora de `.app-body` (que tem `overflow:hidden`). Colocar antes de `</body>` |
| **Refs DOM em IIFE** | Elemento referenciado via `const x = getElementById(...)` no topo do IIFE precisa existir no DOM ao executar o script. Caso contrário, usar lazy: `function getX() { return getElementById(...) }` |
| **Timestamp Python `time.time()`** | Retorna segundos. JS `new Date(ts)` espera ms. Sempre converter: `ts < 1e12 ? ts * 1000 : ts` |
| **Notion `Status` em DB_TALENTOS** | É `select`, não `status`. Update via `{"Status": {"select": {"name": "X"}}}` |
| **Notion `Tipo de contato` em DB_EMAIL/DB_LINKEDIN** | Opções fixas: `Inicial`, `Follow-up`, `Resposta`, `Encerramento`, `Preparação`, `Enfileirado`, `Cadastro CRM`. Valores fora dessa lista fazem o Notion rejeitar silenciosamente |
| **Notion limita rich_text a 2000 chars por segment** | Chunk-ar textos longos em segmentos quando fazendo PATCH (ver `_rich_text` em `update_talento.py`) |

---

## Padrões de integração com SOREN

O dashboard é uma **camada de leitura/escrita sobre o Notion** — não armazena estado próprio. Quem produz os dados são os workflows SOREN no n8n:

- **WF01** (`S4EszbJ2FUnpslG7`) — envio inicial por email. Cria registros `Inicial/Enviado` em `DB_EMAIL`, atualiza `Status=Contato enviado` no talento. Filtro Notion JSON robusto + idempotência 24h.
- **WF03B** (`Ex5CD5McWQS9gC1b`) — polling Gmail. Cria registros `Resposta/Respondido` em `DB_EMAIL` quando candidato responde.
- **WF02 / WF11** — follow-ups por email/LinkedIn.

Quando um workflow do n8n grava algo no Notion, o dashboard reflete na próxima passagem do cache (≤ 3 min) ou imediatamente via botão Refresh.

---

## Histórico de bugs notáveis (lições)

### 1. `interacoes.py` filtrava por relation que não existe
**Erro:** primeira versão filtrava `DB_LINKEDIN`/`DB_EMAIL` por `relation.contains:page_id`, mas o vínculo no Notion é via `Candidato` (rich_text). Nenhum histórico aparecia.
**Fix:** filtro por `Candidato` rich_text em cascata (equals → contains nome → contains primeiro+último). Backend resolve nome via `page_id` quando só recebe ID.

### 2. WF01 enviava 3 emails idênticos em 3 dias consecutivos
**Erro 1:** `Create Interaction Record` mandava `Tipo de contato = "Contato inicial"` (valor inválido). Notion rejeitava o create.
**Erro 2:** `Update Outreach Status` falhava em cascata, então `Status E-mail` no talento nunca virava `Enviado`.
**Erro 3:** `Fetch Talentos` não tinha filtro Notion — pegava 96 talentos.
**Resultado:** mesmo candidato voltava para a fila todo dia e recebia o email de novo.
**Fix:** payload limpo com `Tipo de contato = Inicial`, filtro Notion JSON robusto, idempotência por `Último contato < 24h` no code node como cinto de segurança.

### 3. Epoch 21/01/1970 no timestamp do Kanban
**Erro:** Python `time.time()` retorna segundos; JS `new Date(ts)` espera ms.
**Fix:** `ts < 1e12 ? ts * 1000 : ts` no frontend.

### 4. Botão Refresh no Kanban sem cross-function cache invalidation
**Erro:** PATCH em `/api/update_talento` não invalida cache de `/api/talentos` (instâncias separadas no Vercel).
**Fix:** frontend mantém `_dirty = true` após PATCH; próximo `loadKanban` adiciona `?fresh=1`.

---

## Clonar e rodar em outra máquina

O GitHub guarda **o código**. A Vercel guarda **as configurações e env vars**. O Notion guarda **os dados**. Os três são independentes — nenhum tem cópia dos outros. Esta seção cobre os 3 cenários práticos de uso.

### Pré-requisitos comuns

```bash
# Node.js + Vercel CLI
npm i -g vercel

# Login com sua conta Vercel
vercel login
```

### Cenário A — Mesmo dashboard, na mesma URL, em outra máquina

Use quando você quer apenas continuar trabalhando no mesmo projeto Vercel a partir de outra máquina. **Tempo: ~5 min**.

```bash
git clone https://github.com/kaiobaronips/Tallent_CRM.git
cd Tallent_CRM
vercel link          # vincula a pasta ao projeto "tallent-crm" existente
vercel pull          # baixa env vars locais (sensíveis ficam cifradas)
vercel dev           # roda local em http://localhost:3000
# OU
vercel --prod        # deploy direto pra produção
```

As env vars (`NOTION_TOKEN`, `ANTHROPIC_API_KEY`) já estão no projeto Vercel e não precisam ser configuradas de novo.

### Cenário B — Fork para outra conta Vercel + outro workspace Notion

Use quando você quer criar uma **cópia independente** (outra conta Vercel, outro workspace Notion). **Tempo: ~30 min**.

```bash
git clone https://github.com/kaiobaronips/Tallent_CRM.git
cd Tallent_CRM
vercel               # primeira vez nesta pasta — vai pedir nome novo de projeto
```

Depois:

1. **Criar a integração Notion** em https://www.notion.so/profile/integrations
   - Salvar o token (formato `secret_...`)
2. **Criar 4 databases no Notion** com as mesmas propriedades das originais (ver schemas em [Backends](#backends) — copiar os tipos/opções de `Status`, `Tipo de contato`, `Canal recomendado`, etc.)
   - Talentos
   - Interação E-mail
   - Interação LinkedIn
   - Empresas-alvo
3. **Compartilhar cada database com a integração** (no Notion: `…` → Connections → adicionar a integração)
4. **Pegar os IDs das databases** (da URL do Notion — string de 32 caracteres antes do `?`)
5. **Trocar os IDs hardcoded** nos arquivos Python:
   - `api/data.py` — linhas com `DB_TALENTOS`, `DB_LINKEDIN`, `DB_EMAIL`
   - `api/talentos.py` — `DB_TALENTOS`
   - `api/empresas.py` — `DB_EMPRESAS`
   - `api/interacoes.py` — `DB_LINKEDIN`, `DB_EMAIL`
6. **Configurar env vars na Vercel** (Settings → Environment Variables):
   - `NOTION_TOKEN`
   - `ANTHROPIC_API_KEY` (opcional — sem ela, `/api/insights` cai em heurística e `/api/chat` retorna erro)
7. **Deploy**:
   ```bash
   vercel --prod
   ```

### Cenário C — Rodar 100% local sem Vercel

O `vercel dev` é a forma mais fácil — simula o ambiente serverless local lendo as env vars do projeto Vercel.

```bash
vercel link
vercel pull
vercel dev    # http://localhost:3000
```

Se não quiser usar Vercel nem para dev local, é possível mas exige escrever um pequeno router que mapeia `/api/talentos` → `api/talentos.py:handler`, etc. (cada arquivo já é um `BaseHTTPRequestHandler` standalone). Não é o caminho recomendado.

### Backup das env vars (recomendado)

Em uma máquina já configurada, antes de migrar:

```bash
vercel env pull .env.production
```

Isso baixa as env vars (incluindo segredos) num arquivo local. Mantenha esse arquivo **fora do Git** — o `.gitignore` já cobre `.env*.local`, mas `.env.production` precisa ser adicionado manualmente se quiser usar exatamente esse nome.

### Tabela resumo

| Cenário | Quem você é | Esforço | Notion novo? | Vercel novo? |
|---|---|---|---|---|
| **A** | Você (mesma conta) | 5 min | Não | Não |
| **B** | Você forkando ou outra pessoa | 30 min | Sim | Sim |
| **C** | Dev local | 5 min | Não | Não (usa dev local) |

---

## Deploy & operação

```bash
# Deploy direto (sem CI/CD)
cd /Users/kaiobp/Desktop/tallent-intelligence-crm--dashboard-vercel
vercel --prod
```

- Deploy também é acionado automaticamente pelo hook `Stop` em `.claude/settings.json` ao final de cada sessão Claude Code.
- Variáveis de ambiente (gerenciadas pela Vercel CLI): `NOTION_TOKEN`, `ANTHROPIC_API_KEY`.
- Para puxar localmente: `vercel env pull --environment=production .env.prod` (valores sensíveis vêm vazios — usar diretamente no console Vercel se precisar do valor).

---

## Próximas etapas sugeridas

1. **Aba LinkedIn** — view dedicada do `DB_LINKEDIN` (placeholder existe)
2. **Aba E-mail** — view dedicada do `DB_EMAIL` (placeholder existe)
3. **Aba Workflows / Agentes n8n** — métricas de execução dos WFs
4. **Notificações no card do Kanban** — flag visual quando candidato recebeu resposta nova
5. **Filtros adicionais no Kanban** — por classificação, segmento, perfil
6. **Histórico de mudança de status** — log de quando candidato mudou de coluna

---

## Memória e governança

- **Memory auto-memory** (sessões Claude Code): `~/.claude/projects/-Users-kaiobp/memory/tallent_crm_dashboard.md`
- **Handoffs SOREN**: `/Users/kaiobp/SOREN/RAW/handoffs/handoff-YYYY-MM-DD-*`
- **LOG.md** (source of truth operacional): `/Users/kaiobp/Documents/Obsidian Vault/SOREN/WIKI/LOG.md`

---

**Versão deste README:** 2026-05-21
**Mantido por:** Kaio (operador) + Claude Code (assistente)
