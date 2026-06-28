# M3 — Priorização de Denúncias

Microsserviço responsável por calcular a **prioridade** de cada denúncia classificada, atribuindo um score composto (0–100) e um nível de urgência (CRITICO / ALTO / MEDIO / BAIXO).

## Posição no pipeline

```
M2 (Classificação)  ──► denuncia.classificada ──►  M3 (Priorização)  ──► denuncia.priorizada ──►  M5, M6, M7
M4 (Recorrência)    ──► padrao.recorrencia    ──►  ╝
```

O M3 consome dois tipos de evento do RabbitMQ e publica um terceiro:

| Direção | Routing key           | Origem / Destino |
|---------|-----------------------|-----------------|
| Consome | `denuncia.classificada` | M2              |
| Consome | `padrao.recorrencia`    | M4              |
| Publica | `denuncia.priorizada`   | M5, M6, M7      |

## Algoritmo de score

O score é composto por três parcelas, somadas com cap em 100:

```
score = urgencia_categoria + peso_confianca + boost_recorrencia
```

### 1. Urgência por área (0–40 pts)

Peso fixo definido pela área responsável da denúncia:

| Área                              | Pontos |
|-----------------------------------|--------|
| Saúde                             | 40     |
| Proteção e Direitos Humanos       | 38     |
| Meio Ambiente e Sustentabilidade  | 32     |
| Mobilidade e Trânsito             | 28     |
| Fiscalização e Ordem Pública      | 24     |
| Integridade e Conduta Pública     | 22     |
| Limpeza e Conservação Urbana      | 18     |
| Defesa Animal                     | 15     |
| Educação e Esporte Comunitário    | 12     |
| Defesa do Consumidor              | 10     |
| Encaminhamento Externo            | 8      |
| Triagem Geral                     | 6      |
| _(outras)_                        | 10     |

### 2. Peso da confiança (0–20 pts)

Baseado na certeza da classificação do M2:

- **Alta** → 20 pts
- **Média** → entre 10 e 16 pts (linear pela confiança)
- **Baixa** → proporcional à confiança (0–10 pts)

### 3. Boost de recorrência (0–40 pts)

Crescimento logarítmico baseado na contagem de denúncias semelhantes na mesma região/categoria (dados do M4):

```
boost = 40 × log2(1 + contagem) / log2(51)   [cap 40]
```

| Recorrências | Boost aprox. |
|-------------|-------------|
| 0           | 0 pts       |
| 1           | ~8 pts      |
| 5           | ~21 pts     |
| 15          | ~34 pts     |
| ≥ 50        | 40 pts      |

### Nível final (configurável)

| Nível   | Condição         |
|---------|-----------------|
| CRITICO | score ≥ 75      |
| ALTO    | score ≥ 55      |
| MEDIO   | score ≥ 35      |
| BAIXO   | score < 35      |

## Fluxo de processamento

```
denuncia.classificada
    │
    ├─► Consulta recorrência local (padroes_recorrencia)
    ├─► Calcula score
    ├─► Persiste em denuncias_priorizadas (outbox: publicado=False)
    └─► Publica denuncia.priorizada
            └─► Marca publicado=True (ou relay reprocessa depois)

padrao.recorrencia
    └─► Atualiza cópia local em padroes_recorrencia
```

O **relay** roda em background a cada 30 s e republicar eventos que ficaram com `publicado=False` (ex.: broker fora no momento da publicação).

## Stack

| Camada     | Tecnologia                    |
|------------|-------------------------------|
| API        | FastAPI + Uvicorn             |
| Mensageria | RabbitMQ via aio-pika         |
| Banco      | PostgreSQL (asyncpg + SQLAlchemy 2.0) |
| Validação  | Pydantic v2                   |
| Runtime    | Python 3.12                   |

## Banco de dados

O M3 possui banco próprio (`priorizacao`) — padrão *database-per-service*.

**Tabelas:**

- `denuncias_priorizadas` — resultado de cada priorização + flag de outbox (`publicado`)
- `padroes_recorrencia` — cópia local dos padrões enviados pelo M4; usada para calcular o boost de recorrência das próximas denúncias

## Variáveis de ambiente

Todas com prefixo `M3_` (ou via arquivo `.env`):

| Variável                  | Padrão                                        | Descrição                         |
|---------------------------|-----------------------------------------------|-----------------------------------|
| `M3_RABBITMQ_URL`         | `amqp://guest:guest@rabbitmq:5672/`           | URL de conexão ao RabbitMQ        |
| `M3_EXCHANGE`             | `denuncias`                                   | Exchange topic do RabbitMQ        |
| `M3_FILA`                 | `m3.priorizacao`                              | Fila de consumo                   |
| `M3_ROUTING_CLASSIFICADA` | `denuncia.classificada`                       | Routing key de entrada (M2)       |
| `M3_ROUTING_RECORRENCIA`  | `padrao.recorrencia`                          | Routing key de entrada (M4)       |
| `M3_ROUTING_OUT`          | `denuncia.priorizada`                         | Routing key de saída              |
| `M3_PREFETCH`             | `8`                                           | Prefetch do consumidor            |
| `M3_DATABASE_URL`         | `postgresql+asyncpg://m3:m3@db-m3:5432/priorizacao` | URL do banco PostgreSQL    |
| `M3_CRIAR_TABELAS_NO_STARTUP` | `true`                                   | Cria tabelas automaticamente      |
| `M3_LIMIAR_CRITICO`       | `75.0`                                        | Threshold nível CRITICO           |
| `M3_LIMIAR_ALTO`          | `55.0`                                        | Threshold nível ALTO              |
| `M3_LIMIAR_MEDIO`         | `35.0`                                        | Threshold nível MEDIO             |
| `M3_RELAY_INTERVALO`      | `30`                                          | Intervalo do relay outbox (s)     |
| `M3_LOG_LEVEL`            | `INFO`                                        | Nível de log                      |

## Executando localmente

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t m3-priorizacao .
docker run -p 8000:8000 \
  -e M3_RABBITMQ_URL=amqp://guest:guest@localhost:5672/ \
  -e M3_DATABASE_URL=postgresql+asyncpg://m3:m3@localhost:5432/priorizacao \
  m3-priorizacao
```

## API HTTP

A API de suporte está disponível em `http://localhost:8000`. Documentação interativa: `/docs`.

| Método | Endpoint               | Descrição                                               |
|--------|------------------------|---------------------------------------------------------|
| GET    | `/`                    | Info básica do serviço                                  |
| GET    | `/health`              | Status do banco e do broker                             |
| GET    | `/info`                | Configuração atual (thresholds, urgências, routing keys)|
| POST   | `/priorizar`           | Calcula prioridade avulsa (sem persistência, para testes)|
| GET    | `/denuncias`           | Lista denúncias priorizadas (paginação, filtro por nível/área) |
| GET    | `/denuncias/{id}`      | Busca uma denúncia priorizada pelo ID                   |
| GET    | `/stats`               | Total e contagem por nível                              |

### Exemplo — priorização avulsa

```bash
curl -X POST "http://localhost:8000/priorizar?area_responsavel=Saúde&certeza=Alta&confianca=0.95&contagem_recorrencias=10"
```

Resposta:
```json
{
  "id": "avulso",
  "score": 93.28,
  "nivel": "CRITICO",
  "categoria": null,
  "area_responsavel": "Saúde",
  "urgencia_categoria": 40.0,
  "peso_confianca": 20.0,
  "boost_recorrencia": 33.28,
  "priorizado_em": "2026-06-28T12:00:00Z"
}
```

## Estrutura do projeto

```
app/
├── main.py        # Ciclo de vida FastAPI (startup/shutdown)
├── config.py      # Configurações via variáveis de ambiente
├── models.py      # ORM SQLAlchemy (denuncias_priorizadas, padroes_recorrencia)
├── schemas.py     # Contratos Pydantic (eventos consumidos e publicados)
├── scoring.py     # Algoritmo de score composto
├── processing.py  # Handlers de negócio para cada tipo de evento
├── messaging.py   # Transporte RabbitMQ (consumidor + produtor)
├── repository.py  # Acesso ao banco de dados
├── routes.py      # Endpoints HTTP
└── db.py          # Configuração da sessão AsyncSQLAlchemy
```
