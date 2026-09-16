; ==============================================================================
; MES_Client_Setup.iss
; Script Inno Setup - Instalador Profissional MES Client
; Salcomp - Engenharia de Teste | Manaus
; ==============================================================================
; Como compilar:
;   1. Abra este arquivo no Inno Setup IDE (Compil32.exe) e pressione F9, ou
;   2. Linha de comando:  ISCC.exe installer\MES_Client_Setup.iss
;   O instalador gerado fica em: installer\Output\MES_Client_Setup_v<versao>.exe
;
; Instalacao silenciosa (sem wizard), para escalar em varias estacoes:
;   MES_Client_Setup_v1.0.5.exe /SILENT /PREFIX=FUNC /MODEL=A08 /MACHINE=CAIAPO-M13
;       /TESTER=P2500S /LINE=CAIAPO /CSV="D:\battData" /SYNC="" /DBPASS=senha_do_mes_user
;   Parametros opcionais (com padrao): /DBHOST=172.21.70.184 /DBPORT=5432
;       /DBNAME=mes_db /DBUSER=mes_user /TABLE=mes_results /PREFIX=PCM /TESTER=AUTO
;   /DBPASS e' obrigatorio em modo silencioso (o instalador aborta com mensagem
;   se faltar). Nunca grave a linha com /DBPASS em arquivo.
; ==============================================================================

#define AppName      "MES Client"
#define AppVersion   "1.0.5"
#define AppPublisher "Salcomp - Engenharia de Teste"
#define AppCopyright "Salcomp Manaus 2026"
#define InstallDir   "C:\Utility\MES"
#define ExeName      "MES_Client.exe"

; ==============================================================================
[Setup]
; Identificacao unica do instalador (gere um novo GUID em Tools > Generate GUID)
AppId={{A3F2C1D0-9B4E-4F7A-8C3D-1E6B2A0F5D9C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL=https://salcomp.com.br
AppSupportURL=https://salcomp.com.br
AppCopyright={#AppCopyright}
AppPublisher={#AppPublisher}

; Diretorio de instalacao fixo (producao)
DefaultDirName={#InstallDir}
DisableDirPage=yes

; Sem grupo no menu iniciar
DisableProgramGroupPage=yes

; Saida do instalador gerado
OutputDir=Output
OutputBaseFilename=MES_Client_Setup_v{#AppVersion}

; Icone do instalador
SetupIconFile=..\assets\app.ico

; Compressao maxima
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Requer admin (necessario para Task Scheduler e C:\Utility)
PrivilegesRequired=admin

; Aparencia dark premium
WizardStyle=modern
WizardSizePercent=100

; Imagens dark (geradas em assets/)
WizardImageFile=..\assets\installer_banner.bmp
WizardSmallImageFile=..\assets\installer_header.bmp

; Versao minima do Windows (Windows 7 SP1+)
MinVersion=6.1sp1

UninstallDisplayIcon={app}\{#ExeName}
UninstallDisplayName={#AppName}

; ==============================================================================
[Languages]
Name: "ptBR"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

; ==============================================================================
[Messages]
ptBR.WelcomeLabel1=Bem-vindo ao instalador do [name]
ptBR.WelcomeLabel2=Este assistente instalara o [name/ver] nesta estacao de teste.%n%nAntes de continuar, preencha as informacoes da estacao nas proximas telas.%n%nClique em Avancar para continuar.%n%nBy Parente - Engenharia de Testes Manaus
ptBR.FinishedLabel=A instalacao do [name] foi concluida com sucesso.%n%nClique em Concluir para fechar este assistente.%n%nBy Parente - Engenharia de Testes Manaus

; ==============================================================================
[Files]
; EXE principal
Source: "..\dist\MES_Client.exe"; DestDir: "{app}"; Flags: ignoreversion

; Limites de especificacao
Source: "..\spec_limits.csv";        DestDir: "{app}"; Flags: ignoreversion

; Mapeamento de colunas CSV (editavel via tela MAPEAMENTO da UI)
Source: "..\column_mappings.json";   DestDir: "{app}"; Flags: ignoreversion

; Icone (para o atalho e desinstalador)
Source: "..\assets\app.ico";         DestDir: "{app}\assets"; Flags: ignoreversion

; ==============================================================================
[Icons]
; Atalho na area de trabalho de todos os usuarios
Name: "{commondesktop}\MES Client"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"; Comment: "MES Client - Monitor de Teste Salcomp"

; ==============================================================================
[Run]
; Inicia o MES Client ao finalizar (opcional, usuario pode desmarcar)
Filename: "{app}\{#ExeName}"; Description: "Iniciar MES Client agora"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

; ==============================================================================
[UninstallRun]
; Para o processo antes de desinstalar
Filename: "taskkill.exe"; Parameters: "/F /IM {#ExeName}"; Flags: runhidden; RunOnceId: "StopMES"

; ==============================================================================
[UninstallDelete]
; Remove arquivos gerados pela aplicacao (logs, state, data)
; Mantido comentado para preservar logs em producao
; Type: filesandordirs; Name: "{app}\logs"
; Type: filesandordirs; Name: "{app}\state"
; Type: filesandordirs; Name: "{app}\data"
Type: files; Name: "{app}\config.yaml"
; O .env guarda a senha do banco - nao pode ficar para tras na desinstalacao
Type: files; Name: "{app}\.env"

; ==============================================================================
[Code]
{ ============================================================================
  Paginas customizadas do wizard para configuracao da estacao
  Escrito em Pascal Script (linguagem nativa do Inno Setup)

  Todos os campos aceitam valor pela linha de comando (/NOME=valor). Em modo
  /SILENT as paginas nao aparecem e os valores usados sao exatamente os dos
  parametros (ou o padrao de cada campo).
  ============================================================================ }

var
  { Pagina 1: Prefixo, modelo, ID da maquina, tipo do testador }
  PageEstacao: TInputQueryWizardPage;

  { Pagina 2: Linha de producao e pasta CSV }
  PageConfig: TInputQueryWizardPage;

  { Pagina 3: Banco de dados - conexao (host, porta, nome, usuario) }
  PageBanco: TInputQueryWizardPage;

  { Pagina 4: Banco de dados - senha e tabela, em pagina propria.
    Ate a v1.0.5 estes dois campos ficavam juntos com os 4 de cima (6 campos
    na mesma pagina). O TInputQueryWizardPage do Inno Setup nao redimensiona
    a janela do wizard por pagina: com 6 campos e rotulos longos, os dois
    ultimos (Senha e Tabela) ficavam fora da area visivel — o tecnico via so
    4 campos e, ao clicar Avancar, o instalador acusava "informe a senha"
    sem ela nunca ter aparecido na tela. Separar em pagina propria garante
    que a senha sempre fica visivel. }
  PageSenha: TInputQueryWizardPage;

  { Pagina 5: Copia para a rede (Samba) }
  PageSync: TInputQueryWizardPage;

  { Ultimo valor que o instalador sugeriu sozinho para a pasta CSV / Samba.
    Se o tecnico nao mexeu, o instalador pode recalcular quando o modelo muda. }
  CsvSugerido:  String;
  SyncSugerido: String;


{ --------------------------------------------------------------------------
  Param: le /NOME=valor da linha de comando, com padrao
  -------------------------------------------------------------------------- }
function Param(Nome, Padrao: String): String;
begin
  Result := ExpandConstant('{param:' + Nome + '|' + Padrao + '}');
end;


{ --------------------------------------------------------------------------
  Sugestoes por tipo de estacao
  PCM  : estacoes PCM Tester (TestPad) - CSV em subpastas por modelo
  FUNC : Teste Funcional BW P2500S (Caiapo) - grava tudo em D:\battData
  TABC : Tab Cutting BW P2500S (Caiapo)
  -------------------------------------------------------------------------- }
function SugerirCsv(Prefixo, Modelo: String): String;
begin
  if Prefixo = 'PCM' then
    Result := 'D:\Testpad software\CSV\' + Modelo
  else
    Result := 'D:\battData';
end;

function SugerirSync(Prefixo, Modelo, DbHost: String): String;
begin
  { Nas estacoes PCM o servidor de arquivos e o mesmo host do banco. Nas
    demais linhas nao ha essa coincidencia - fica vazio e o tecnico preenche
    se houver share definido. Vazio = sync desligado. }
  if (Prefixo = 'PCM') and (DbHost <> '') then
    Result := '\\' + DbHost + '\NonAlphaSec2Info\logs\' + Modelo
  else
    Result := '';
end;


{ --------------------------------------------------------------------------
  InitializeWizard: executado uma vez ao abrir o wizard
  Cria todas as paginas customizadas aqui
  -------------------------------------------------------------------------- }
procedure InitializeWizard;
begin
  { --- PAGINA 1: Configuracao da Estacao --- }
  PageEstacao := CreateInputQueryPage(
    wpWelcome,
    'Configuração da Estação',
    'Informe os dados da estação de teste',
    'Preencha os campos abaixo. Estas informações serão gravadas no arquivo config.yaml.'
  );

  PageEstacao.Add('Tipo da estação / prefixo do ID (PCM, FUNC ou TABC):', False);
  PageEstacao.Add('Modelo do produto (ex: A06, A17, A16, A08):', False);
  PageEstacao.Add('ID da máquina (ex: BR-PCMTEST-01, CAIAPO-M13):', False);
  PageEstacao.Add('Tipo do testador (AUTO, PCM_TESTER, CYG ou P2500S):', False);

  PageEstacao.Values[0] := UpperCase(Param('PREFIX',  'PCM'));
  PageEstacao.Values[1] := UpperCase(Param('MODEL',   'A17'));
  PageEstacao.Values[2] := UpperCase(Param('MACHINE', 'BR-PCMTEST-01'));
  PageEstacao.Values[3] := UpperCase(Param('TESTER',  'AUTO'));

  { --- PAGINA 2: Linha e CSV --- }
  PageConfig := CreateInputQueryPage(
    PageEstacao.ID,
    'Configuração de Arquivos',
    'Linha de produção e pasta dos CSVs',
    'Informe a linha de produção e a pasta onde o testador salva os arquivos CSV desta estação.'
  );

  PageConfig.Add('Linha de produção (ex: NAVAJO, TOMAHAWK, CAIAPO):', False);
  PageConfig.Add('Pasta dos CSVs do testador:', False);

  CsvSugerido := SugerirCsv(PageEstacao.Values[0], PageEstacao.Values[1]);
  PageConfig.Values[0] := UpperCase(Param('LINE', 'NAVAJO'));
  PageConfig.Values[1] := Param('CSV', CsvSugerido);

  { --- PAGINA 3: Banco de Dados --- }
  PageBanco := CreateInputQueryPage(
    PageConfig.ID,
    'Configuração do Banco de Dados',
    'Conexão com o PostgreSQL do servidor Salcomp',
    'Em produção, mantenha os valores padrão. Altere somente se o servidor mudou.'
  );

  PageBanco.Add('Host do servidor (IP ou nome):', False);
  PageBanco.Add('Porta PostgreSQL:', False);
  PageBanco.Add('Nome do banco:', False);
  PageBanco.Add('Usuário do banco:', False);

  { Host tem padrao porque so existe um servidor de producao (172.21.70.184).
    Nao e' segredo — e' o endereco interno da rede da fabrica, ja documentado
    em varios arquivos deste repositorio. A SENHA continua sem padrao aqui de
    proposito: este .iss e' publico no GitHub, e gravar a senha real do banco
    num arquivo que qualquer pessoa pode ler tornaria a credencial permanente
    (mesmo apagada depois, continuaria recuperavel pelo historico do Git —
    exatamente o problema que o commit 20e76ef corrigiu). O tecnico digita a
    senha na instalacao (pagina seguinte) ou passa /DBPASS no modo silencioso,
    nunca gravado em arquivo. }
  PageBanco.Values[0] := Param('DBHOST', '172.21.70.184');
  PageBanco.Values[1] := Param('DBPORT', '5432');
  PageBanco.Values[2] := Param('DBNAME', 'mes_db');
  PageBanco.Values[3] := Param('DBUSER', 'mes_user');

  { --- PAGINA 4: Senha e tabela (separada da pagina 3, ver comentario na
    declaracao de PageSenha acima) --- }
  PageSenha := CreateInputQueryPage(
    PageBanco.ID,
    'Credenciais do Banco de Dados',
    'Senha de acesso e tabela de resultados',
    'A senha é gravada apenas no arquivo .env da estação, nunca no config.yaml.'
  );

  PageSenha.Add('Senha do banco:', True);  { True = oculta a senha }
  PageSenha.Add('Tabela de resultados:', False);

  PageSenha.Values[0] := Param('DBPASS', '');
  PageSenha.Values[1] := Param('TABLE',  'mes_results');

  { --- PAGINA 5: Copia para a rede --- }
  PageSync := CreateInputQueryPage(
    PageSenha.ID,
    'Cópia dos CSVs para a rede',
    'Compartilhamento de destino (opcional)',
    'Se esta estação também deve copiar os CSVs para um compartilhamento de rede, informe a pasta UNC. Deixe vazio para não copiar.'
  );

  PageSync.Add('Pasta de destino (ex: \\servidor\share\logs\A17). Vazio = não copiar:', False);

  SyncSugerido := SugerirSync(PageEstacao.Values[0], PageEstacao.Values[1], PageBanco.Values[0]);
  PageSync.Values[0] := Param('SYNC', SyncSugerido);
end;


{ --------------------------------------------------------------------------
  NextButtonClick: validacao ao clicar em Avancar em cada pagina
  Retorna False para impedir avancar se algum campo estiver invalido
  -------------------------------------------------------------------------- }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Prefixo, Modelo, MaquinaID, Tester, Novo: String;
begin
  Result := True;

  if CurPageID = PageEstacao.ID then begin
    Prefixo   := UpperCase(Trim(PageEstacao.Values[0]));
    Modelo    := UpperCase(Trim(PageEstacao.Values[1]));
    MaquinaID := UpperCase(Trim(PageEstacao.Values[2]));
    Tester    := UpperCase(Trim(PageEstacao.Values[3]));

    if (Prefixo <> 'PCM') and (Prefixo <> 'FUNC') and (Prefixo <> 'TABC') then begin
      MsgBox('Tipo da estação deve ser PCM, FUNC ou TABC.', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    if Modelo = '' then begin
      MsgBox('Por favor, informe o modelo do produto (ex: A06, A17, A08).', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    if MaquinaID = '' then begin
      MsgBox('Por favor, informe o ID da máquina (ex: BR-PCMTEST-01).', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    if (Tester <> 'AUTO') and (Tester <> 'PCM_TESTER') and (Tester <> 'CYG') and (Tester <> 'P2500S') then begin
      MsgBox('Tipo do testador deve ser AUTO, PCM_TESTER, CYG ou P2500S.' + #13#10 +
             'AUTO detecta o formato pelo próprio arquivo e serve para todos.', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    { Grava normalizado }
    PageEstacao.Values[0] := Prefixo;
    PageEstacao.Values[1] := Modelo;
    PageEstacao.Values[2] := MaquinaID;
    PageEstacao.Values[3] := Tester;

    { Recalcula a pasta CSV sugerida - so se o tecnico nao alterou a sugestao anterior }
    Novo := SugerirCsv(Prefixo, Modelo);
    if (Trim(PageConfig.Values[1]) = '') or (PageConfig.Values[1] = CsvSugerido) then
      PageConfig.Values[1] := Novo;
    CsvSugerido := Novo;
  end;

  if CurPageID = PageConfig.ID then begin
    if Trim(PageConfig.Values[0]) = '' then begin
      MsgBox('Por favor, informe a linha de produção.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(PageConfig.Values[1]) = '' then begin
      MsgBox('Por favor, informe a pasta dos CSVs do testador.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    PageConfig.Values[0] := UpperCase(Trim(PageConfig.Values[0]));
  end;

  { Host tem padrao (172.21.70.184) mas ainda assim confere: se o tecnico
    apagou o campo para digitar outro servidor e deixou vazio por engano, a
    estacao ficaria sem conseguir conectar, com erro so' aparecendo no log. }
  if CurPageID = PageBanco.ID then begin
    if Trim(PageBanco.Values[0]) = '' then begin
      MsgBox('Informe o host do servidor PostgreSQL.' + #13#10 +
             'Peca o endereco a engenharia se nao souber.', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    { Sugere o share so agora, que o host do banco e' conhecido }
    Novo := SugerirSync(PageEstacao.Values[0], PageEstacao.Values[1], Trim(PageBanco.Values[0]));
    if (Trim(PageSync.Values[0]) = '') or (PageSync.Values[0] = SyncSugerido) then
      PageSync.Values[0] := Novo;
    SyncSugerido := Novo;
  end;

  if CurPageID = PageSenha.ID then begin
    if Trim(PageSenha.Values[0]) = '' then begin
      MsgBox('Informe a senha do banco.' + #13#10 +
             'Ela sera gravada no arquivo .env da estacao, nunca no config.yaml.',
             mbError, MB_OK);
      Result := False;
      Exit;
    end;

    if Trim(PageSenha.Values[1]) = '' then
      PageSenha.Values[1] := 'mes_results';
  end;
end;


{ --------------------------------------------------------------------------
  PrepareToInstall: ultima chance de abortar. Em modo silencioso as paginas
  nao rodam NextButtonClick, entao os campos obrigatorios sao conferidos
  aqui. Retornar texto nao vazio cancela a instalacao mostrando a mensagem.
  -------------------------------------------------------------------------- }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Prefixo, Tester: String;
begin
  Result := '';
  if not WizardSilent then
    Exit;

  Prefixo := UpperCase(Trim(PageEstacao.Values[0]));
  Tester  := UpperCase(Trim(PageEstacao.Values[3]));

  if Trim(PageSenha.Values[0]) = '' then
    Result := 'Modo silencioso: informe /DBPASS=<senha do banco>.'
  else if (Prefixo <> 'PCM') and (Prefixo <> 'FUNC') and (Prefixo <> 'TABC') then
    Result := 'Modo silencioso: /PREFIX deve ser PCM, FUNC ou TABC.'
  else if (Tester <> 'AUTO') and (Tester <> 'PCM_TESTER') and (Tester <> 'CYG') and (Tester <> 'P2500S') then
    Result := 'Modo silencioso: /TESTER deve ser AUTO, PCM_TESTER, CYG ou P2500S.'
  else if Trim(PageConfig.Values[1]) = '' then
    Result := 'Modo silencioso: informe /CSV=<pasta dos CSVs>.';
end;


{ --------------------------------------------------------------------------
  BuildStationId: monta o ID da estacao no padrao PREFIXO_MODELO_MAQUINA
  Ex.: PCM_A17_BR-PCMTEST-01, FUNC_A08_CAIAPO-M13, TABC_A08_CAIAPO-M13
  -------------------------------------------------------------------------- }
function BuildStationId: String;
begin
  Result := UpperCase(Trim(PageEstacao.Values[0]))
          + '_' + UpperCase(Trim(PageEstacao.Values[1]))
          + '_' + UpperCase(Trim(PageEstacao.Values[2]));
end;


function BoolStr(B: Boolean): String;
begin
  if B then Result := 'true' else Result := 'false';
end;


{ --------------------------------------------------------------------------
  GenerateConfig: grava o .env e o config.yaml na pasta de instalacao

  Duas regras importantes para producao:

  1. A SENHA DO BANCO vai para o .env, nunca para o config.yaml. O config
     guarda apenas o placeholder da variavel MES_DB_PASSWORD, que o
     config/loader.py resolve na hora de conectar.
     ATENCAO: nao escreva a sintaxe completa do placeholder aqui dentro -
     a chave de fechamento encerraria este comentario Pascal antes da hora.

  2. ATUALIZACAO PRESERVA O CONFIG DA ESTACAO. Se ja' existe um config.yaml,
     ele nao e' sobrescrito - a estacao ja' foi configurada, possivelmente
     ajustada a mao depois da instalacao, e reinstalar por cima para atualizar
     a versao nao pode zerar isso. O .env e' sempre reescrito, porque a senha
     vem do formulario e pode ter mudado.

  Derivados do tipo do testador:
     - log.recursive: true so para PCM_TESTER (TestPad grava em subpastas por
       modelo). P2500S e CYG gravam tudo numa pasta so.
     - spec_check.enabled: true so para PCM_TESTER. O P2500S traz Max/Min em
       cada linha e o spec_limits.csv nao cobre esses modelos.
  -------------------------------------------------------------------------- }
procedure GenerateConfig;
var
  StationId:   String;
  Model:       String;
  Tester:      String;
  Line:        String;
  CsvFolder:   String;
  DbHost:      String;
  DbPort:      String;
  DbName:      String;
  DbUser:      String;
  DbPass:      String;
  DbTable:     String;
  SyncDest:    String;
  SyncOn:      Boolean;
  IsPcm:       Boolean;
  ConfigPath:  String;
  EnvPath:     String;
  Content:     String;
begin
  StationId  := BuildStationId;
  Model      := UpperCase(Trim(PageEstacao.Values[1]));
  Tester     := UpperCase(Trim(PageEstacao.Values[3]));
  Line       := UpperCase(Trim(PageConfig.Values[0]));
  CsvFolder  := Trim(PageConfig.Values[1]);
  DbHost     := Trim(PageBanco.Values[0]);
  DbPort     := Trim(PageBanco.Values[1]);
  DbName     := Trim(PageBanco.Values[2]);
  DbUser     := Trim(PageBanco.Values[3]);
  DbPass     := Trim(PageSenha.Values[0]);
  DbTable    := Trim(PageSenha.Values[1]);
  SyncDest   := Trim(PageSync.Values[0]);
  SyncOn     := SyncDest <> '';
  IsPcm      := Tester = 'PCM_TESTER';
  ConfigPath := ExpandConstant('{app}\config.yaml');
  EnvPath    := ExpandConstant('{app}\.env');

  if Tester = '' then Tester := 'AUTO';
  if DbTable = '' then DbTable := 'mes_results';

  { --- .env: sempre reescrito, e' onde a senha do banco mora --- }
  SaveStringToFile(EnvPath, 'MES_DB_PASSWORD=' + DbPass + #13#10, False);

  { --- config.yaml: preservado se a estacao ja' esta' configurada --- }
  if FileExists(ConfigPath) then
    Exit;

  { Substitui barras invertidas por barras normais para o YAML }
  StringChangeEx(CsvFolder, '\', '/', False);

  Content :=
    'database:'                                              + #13#10 +
    '  enabled: true'                                        + #13#10 +
    '  host: '     + DbHost                                  + #13#10 +
    '  port: '     + DbPort                                  + #13#10 +
    '  name: '     + DbName                                  + #13#10 +
    '  user: '     + DbUser                                  + #13#10 +
    '  password: ${MES_DB_PASSWORD}'                         + #13#10 +
    '  table: '    + DbTable                                 + #13#10 +
    '  jsonb_index: false'                                   + #13#10 +
    ''                                                       + #13#10 +
    'station:'                                               + #13#10 +
    '  id: '       + StationId                               + #13#10 +
    '  type: '     + Tester                                  + #13#10 +
    '  model: '    + Model                                   + #13#10 +
    '  line: '     + Line                                    + #13#10 +
    ''                                                       + #13#10 +
    'log:'                                                   + #13#10 +
    '  folder: '   + CsvFolder                               + #13#10 +
    '  recursive: ' + BoolStr(IsPcm)                         + #13#10 +
    ''                                                       + #13#10 +
    'operation:'                                             + #13#10 +
    '  mode: both'                                           + #13#10 +
    ''                                                       + #13#10 +
    'sync:'                                                  + #13#10 +
    '  enabled: ' + BoolStr(SyncOn)                          + #13#10 +
    '  destination_folder: "' + SyncDest + '"'               + #13#10 +
    '  mode: diff'                                           + #13#10 +
    ''                                                       + #13#10 +
    'parser:'                                                + #13#10 +
    '  scan_interval: 5'                                     + #13#10 +
    ''                                                       + #13#10 +
    'spec_check:'                                            + #13#10 +
    '  enabled: ' + BoolStr(IsPcm)                           + #13#10 +
    '  file: spec_limits.csv'                                + #13#10 +
    ''                                                       + #13#10 +
    'auth:'                                                  + #13#10 +
    '  operador_password: ""'                                + #13#10 +
    '  engenharia_password: "admin"'                         + #13#10;

  SaveStringToFile(ConfigPath, Content, False);
end;


{ --------------------------------------------------------------------------
  RegisterTaskScheduler: cria tarefa de auto-start via schtasks.exe
  Usa linha de comando porque o Pascal nao tem acesso direto ao COM do Windows
  -------------------------------------------------------------------------- }
procedure RegisterTaskScheduler;
var
  ExePath:  String;
  TaskXml:  String;
  XmlPath:  String;
  ResultCode: Integer;
begin
  ExePath := ExpandConstant('{app}\{#ExeName}');
  XmlPath := ExpandConstant('{tmp}\mes_task.xml');

  { Gera XML da tarefa agendada — mais confiavel que parametros do schtasks }
  TaskXml :=
    '<?xml version="1.0" encoding="UTF-16"?>'                                   + #13#10 +
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' + #13#10 +
    '  <Triggers>'                                                               + #13#10 +
    '    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>'                   + #13#10 +
    '  </Triggers>'                                                              + #13#10 +
    '  <Principals>'                                                             + #13#10 +
    '    <Principal id="Author">'                                                + #13#10 +
    '      <RunLevel>HighestAvailable</RunLevel>'                                + #13#10 +
    '    </Principal>'                                                           + #13#10 +
    '  </Principals>'                                                            + #13#10 +
    '  <Settings>'                                                               + #13#10 +
    '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>'           + #13#10 +
    '    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>'                          + #13#10 +
    '    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>' + #13#10 +
    { Sem estas quatro linhas o Task Scheduler aplica os padroes dele, que
      impedem a estacao de coletar: nao inicia se estiver em bateria, para
      se cair para bateria, e para quando a maquina deixa de estar ociosa.
      Numa estacao ligada a nobreak que se reporta como bateria, isso
      significa cliente parado sem ninguem perceber. }
    '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'         + #13#10 +
    '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>'                 + #13#10 +
    '    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd>'                     +
    '<RestartOnIdle>false</RestartOnIdle></IdleSettings>'                        + #13#10 +
    '    <StartWhenAvailable>true</StartWhenAvailable>'                          + #13#10 +
    '  </Settings>'                                                              + #13#10 +
    '  <Actions>'                                                                + #13#10 +
    '    <Exec>'                                                                 + #13#10 +
    '      <Command>' + ExePath + '</Command>'                                   + #13#10 +
    '      <WorkingDirectory>' + ExpandConstant('{app}') + '</WorkingDirectory>' + #13#10 +
    '    </Exec>'                                                                + #13#10 +
    '  </Actions>'                                                               + #13#10 +
    '</Task>';

  SaveStringToFile(XmlPath, TaskXml, False);

  { Importa a tarefa via schtasks /Create }
  Exec('schtasks.exe',
       '/Create /TN "MES_Client_Autostart" /XML "' + XmlPath + '" /F',
       '',
       SW_HIDE,
       ewWaitUntilTerminated,
       ResultCode);
end;


{ --------------------------------------------------------------------------
  CurStepChanged: gancho chamado em cada transicao de passo da instalacao
  ssPostInstall = apos copiar todos os arquivos
  -------------------------------------------------------------------------- }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    { Cria subpastas necessarias para o runtime }
    ForceDirectories(ExpandConstant('{app}\logs'));
    ForceDirectories(ExpandConstant('{app}\state'));
    ForceDirectories(ExpandConstant('{app}\data'));

    { Gera o config.yaml personalizado para esta estacao }
    GenerateConfig;

    { Registra a tarefa de auto-start no Windows Task Scheduler }
    RegisterTaskScheduler;
  end;
end;


{ --------------------------------------------------------------------------
  CurUninstallStepChanged: gancho durante desinstalacao
  usUninstall = logo antes de remover os arquivos
  -------------------------------------------------------------------------- }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    { Para o processo MES Client se estiver rodando }
    Exec('taskkill.exe', '/F /IM {#ExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    { Remove a tarefa do Task Scheduler }
    Exec('schtasks.exe', '/Delete /TN "MES_Client_Autostart" /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;


{ --------------------------------------------------------------------------
  UpdateReadyMemo: texto exibido na pagina "Pronto para instalar"
  Mostra um resumo do que sera feito
  -------------------------------------------------------------------------- }
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  StationId:  String;
  ConfigAcao: String;
  SyncTxt:    String;
begin
  StationId := BuildStationId;

  { Avisa o tecnico se esta e' uma atualizacao sobre estacao ja' configurada }
  if FileExists(ExpandConstant('{app}\config.yaml')) then
    ConfigAcao := 'Preservar o config.yaml existente desta estação (campos acima serão ignorados)'
  else
    ConfigAcao := 'Gerar config.yaml para esta estação';

  if Trim(PageSync.Values[0]) = '' then
    SyncTxt := '(desligada)'
  else
    SyncTxt := Trim(PageSync.Values[0]);

  Result :=
    'Estação configurada:' + NewLine +
    Space + 'Station ID  : ' + StationId                                    + NewLine +
    Space + 'Modelo      : ' + UpperCase(Trim(PageEstacao.Values[1]))       + NewLine +
    Space + 'Máquina     : ' + UpperCase(Trim(PageEstacao.Values[2]))       + NewLine +
    Space + 'Testador    : ' + UpperCase(Trim(PageEstacao.Values[3]))       + NewLine +
    Space + 'Linha       : ' + UpperCase(Trim(PageConfig.Values[0]))        + NewLine +
    Space + 'Pasta CSV   : ' + Trim(PageConfig.Values[1])                   + NewLine +
    Space + 'Banco       : ' + Trim(PageBanco.Values[0]) + ':' + Trim(PageBanco.Values[1]) + '/' + Trim(PageBanco.Values[2]) + '  tabela ' + Trim(PageSenha.Values[1]) + NewLine +
    Space + 'Cópia rede  : ' + SyncTxt                                      + NewLine +
    NewLine +
    'Ações que serão executadas:' + NewLine +
    Space + 'Copiar MES_Client.exe para C:\Utility\MES'                     + NewLine +
    Space + ConfigAcao                                                      + NewLine +
    Space + 'Gravar a senha do banco no arquivo .env'                       + NewLine +
    Space + 'Registrar inicialização automática (Task Scheduler)'           + NewLine +
    Space + 'Criar atalho na Área de Trabalho';
end;
