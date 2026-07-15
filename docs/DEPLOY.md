# Guia de Deploy — MES Client v1.0.3

Procedimento para implantar/atualizar o MES Client nas estações PCM Tester da
linha de produção (Salcomp Manaus).

## O que muda nesta versão (v1.0.2 → v1.0.3)

`parser/cyg_parser.py` ganhou um gate de validação: linhas de cabeçalho
repetido, linhas truncadas, excesso de colunas e lixo binário (cauda de CSV
corrompida) agora são **rejeitadas antes do INSERT**, em vez de irem para o
banco e precisarem ser filtradas depois no dashboard. Cada rejeição é logada
com o motivo e a linha de origem; um contador (`session_rows_skipped`)
acompanha quantas linhas foram puladas na sessão atual.

**Isso não deveria afetar o funcionamento normal** — CSVs bem formados
continuam sendo lidos exatamente como antes. Ele só muda o comportamento
quando o arquivo de origem já está corrompido (cauda truncada, escrita
interrompida), caso em que a linha ruim deixa de ir para o banco.

## Antes de instalar em produção

1. **Rodar a regressão contra os CSVs reais da estação**, para confirmar que
   nenhuma linha legítima é rejeitada:
   ```powershell
   cd D:\MES_Client_Complete
   python tests\regression_real_files.py
   ```
   Isso lê os arquivos listados em `offsets.json` (os CSVs reais que a
   estação já processou) do zero e reporta quantas linhas seriam aceitas vs.
   rejeitadas, sem escrever no banco. **Se qualquer linha esperada aparecer
   como rejeitada, pare e investigue antes de prosseguir** — pode ser um
   padrão de CSV real que o gate ainda não reconhece.

2. Rodar o teste sintético (rápido, sem banco, não depende dos arquivos da
   estação):
   ```powershell
   python tests\test_parser_validation.py
   ```

## Instalação (por estação)

1. Copie `installer\Output\MES_Client_Setup_v1.0.3.exe` para a estação (via
   pendrive ou rede).
2. Se já existe uma instalação anterior rodando, feche-a pelo ícone da
   bandeja (STOP/EXIT) antes de instalar por cima.
3. Execute o instalador **como Administrador**.
4. No wizard, confirme modelo, ID da máquina, pasta de CSVs e dados do banco
   — o instalador tenta reaproveitar `config.yaml` existente se já houver um.
5. Ao final, o MES Client inicia automaticamente (ícone na bandeja).

## Verificação pós-instalação

1. Ícone da bandeja **verde** = monitor ativo, dados sendo enviados.
2. Abra o log (`logs\client.log`, ou tela STATUS na bandeja) e confirme:
   ```
   MONITOR INICIADO
   Pasta monitorada: <pasta configurada>
   ```
3. **Novo nesta versão** — se aparecer uma linha como:
   ```
   N linha(s) rejeitada(s) em <arquivo>: #123(garbage_chars), #124(header_repeat) ...
   ```
   isso é o gate de validação funcionando (rejeitando dado ruim antes do
   banco) — não é um erro do cliente. Só investigue se o **volume** de
   rejeições for muito maior do que o esperado pela regressão do passo
   anterior, o que indicaria um padrão de CSV real ainda não coberto.
4. Confirme no dashboard (mes-server) que a estação aparece com dados novos
   dentro de alguns minutos.

## Rollback

Se algo der errado, o instalador anterior (`MES_Client_Setup_v1.0.2.exe`,
se ainda disponível) pode ser reinstalado por cima — `config.yaml` da
estação não é sobrescrito pelo instalador quando já existe.

## Homologação de múltiplas estações

Repita "Instalação" e "Verificação pós-instalação" em cada estação
individualmente. Não há dependência entre estações — uma instalação com
problema não afeta as demais.
