; ==============================================================================
; MES_Client_Setup.iss
; Script Inno Setup - Instalador Profissional MES Client
; Salcomp - Engenharia de Teste | Manaus
; ==============================================================================
; Como compilar:
;   1. Abra este arquivo no Inno Setup IDE (Compil32.exe)
;   2. Pressione F9 (ou Build > Compile)
;   3. O instalador gerado fica em: installer\Output\MES_Client_Setup.exe
; ==============================================================================

#define AppName      "MES Client"
#define AppVersion   "1.0.2"
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

; Nao permite instalacao em modo silencioso sem parametros
; (garante que o tecnico preencha o formulario da estacao)
UninstallDisplayIcon={app}\{#ExeName}
UninstallDisplayName={#AppName}

; ==============================================================================
[Languages]
Name: "ptBR"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

; ==============================================================================
[Messages]
ptBR.WelcomeLabel1=Bem-vindo ao instalador do [name]
ptBR.WelcomeLabel2=Este assistente instalara o [name/ver] na estacao PCM Tester.%n%nAntes de continuar, preencha as informacoes da estacao nas proximas telas.%n%nClique em Avancar para continuar.
ptBR.FinishedLabel=A instalacao do [name] foi concluida com sucesso.%n%nClique em Concluir para fechar este assistente.

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
Name: "{commondesktop}\MES Client"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"; Comment: "MES Client - Monitor de Teste PCM Salcomp"

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

; ==============================================================================
[Code]
{ ============================================================================
  Paginas customizadas do wizard para configuracao da estacao
  Escrito em Pascal Script (linguagem nativa do Inno Setup)
  ============================================================================ }

var
  { Pagina 1: Modelo e ID da maquina }
  PageEstacao: TInputQueryWizardPage;

  { Pagina 2: Linha de producao e pasta CSV }
  PageConfig: TInputQueryWizardPage;

  { Pagina 3: Banco de dados }
  PageBanco: TInputQueryWizardPage;



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
    'Informe os dados da estação PCM Tester',
    'Preencha os campos abaixo. Estas informações serão gravadas no arquivo config.yaml.'
  );

  { Campo: Modelo do produto (dropdown) }
  { Inno Setup nao tem CreateComboPage nativo — usamos label + edit e instruimos o tecnico }
  PageEstacao.Add('Modelo do produto (ex: A06, A17, A16, A13):', False);
  PageEstacao.Add('ID da máquina (ex: BR-PCMTEST-01):', False);

  { Valores padrao }
  PageEstacao.Values[0] := 'A17';
  PageEstacao.Values[1] := 'BR-PCMTEST-01';

  { --- PAGINA 2: Linha e CSV --- }
  PageConfig := CreateInputQueryPage(
    PageEstacao.ID,
    'Configuração de Arquivos',
    'Linha de produção e pasta dos CSVs',
    'Informe a linha de produção e onde o TestPad salva os arquivos CSV desta estação.'
  );

  PageConfig.Add('Linha de produção (ex: NAVAJO, TOMAHAWK):', False);
  PageConfig.Add('Pasta dos CSVs do TestPad:', False);

  PageConfig.Values[0] := 'NAVAJO';
  PageConfig.Values[1] := 'D:\Testpad software\CSV\A17';

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
  PageBanco.Add('Senha do banco:', True);  { True = oculta a senha }

  PageBanco.Values[0] := '172.21.70.184';
  PageBanco.Values[1] := '5432';
  PageBanco.Values[2] := 'mes_db';
  PageBanco.Values[3] := 'mes_user';
  PageBanco.Values[4] := 'mes123';
end;


{ --------------------------------------------------------------------------
  NextButtonClick: validacao ao clicar em Avancar em cada pagina
  Retorna False para impedir avancar se algum campo estiver vazio
  -------------------------------------------------------------------------- }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Modelo, MaquinaID: String;
begin
  Result := True;

  if CurPageID = PageEstacao.ID then begin
    Modelo    := Trim(PageEstacao.Values[0]);
    MaquinaID := Trim(PageEstacao.Values[1]);

    if Modelo = '' then begin
      MsgBox('Por favor, informe o modelo do produto (ex: A06, A17).', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    if MaquinaID = '' then begin
      MsgBox('Por favor, informe o ID da máquina (ex: BR-PCMTEST-01).', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    { Atualiza o campo CSV com o modelo digitado }
    PageConfig.Values[1] := 'D:\Testpad software\CSV\' + UpperCase(Modelo);
  end;

  if CurPageID = PageConfig.ID then begin
    if Trim(PageConfig.Values[1]) = '' then begin
      MsgBox('Por favor, informe a pasta dos CSVs do TestPad.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;


{ --------------------------------------------------------------------------
  BuildStationId: monta o ID da estacao no padrao PCM_MODELO_MAQUINA
  -------------------------------------------------------------------------- }
function BuildStationId: String;
begin
  Result := 'PCM_' + UpperCase(Trim(PageEstacao.Values[0]))
                   + '_' + UpperCase(Trim(PageEstacao.Values[1]));
end;


{ --------------------------------------------------------------------------
  GenerateConfig: grava o config.yaml na pasta de instalacao
  Usa o formato YAML com os valores digitados pelo tecnico
  -------------------------------------------------------------------------- }
procedure GenerateConfig;
var
  StationId:   String;
  Model:       String;
  Line:        String;
  CsvFolder:   String;
  DbHost:      String;
  DbPort:      String;
  DbName:      String;
  DbUser:      String;
  DbPass:      String;
  SyncDest:    String;
  ConfigPath:  String;
  Content:     String;
begin
  StationId  := BuildStationId;
  Model      := UpperCase(Trim(PageEstacao.Values[0]));
  Line       := UpperCase(Trim(PageConfig.Values[0]));
  CsvFolder  := Trim(PageConfig.Values[1]);
  DbHost     := Trim(PageBanco.Values[0]);
  DbPort     := Trim(PageBanco.Values[1]);
  DbName     := Trim(PageBanco.Values[2]);
  DbUser     := Trim(PageBanco.Values[3]);
  DbPass     := Trim(PageBanco.Values[4]);
  SyncDest   := '\\' + DbHost + '\NonAlphaSec2Info\logs\' + Model;
  ConfigPath := ExpandConstant('{app}\config.yaml');

  { Substitui barras invertidas por barras normais para o YAML }
  StringChangeEx(CsvFolder, '\', '/', False);

  Content :=
    'database:'                                              + #13#10 +
    '  enabled: true'                                        + #13#10 +
    '  host: '     + DbHost                                  + #13#10 +
    '  port: '     + DbPort                                  + #13#10 +
    '  name: '     + DbName                                  + #13#10 +
    '  user: '     + DbUser                                  + #13#10 +
    '  password: ' + DbPass                                  + #13#10 +
    '  table: mes_test_results'                              + #13#10 +
    ''                                                       + #13#10 +
    'station:'                                               + #13#10 +
    '  id: '       + StationId                               + #13#10 +
    '  type: PCM_TESTER'                                     + #13#10 +
    '  model: '    + Model                                   + #13#10 +
    '  line: '     + Line                                    + #13#10 +
    ''                                                       + #13#10 +
    'log:'                                                   + #13#10 +
    '  folder: '   + CsvFolder                               + #13#10 +
    '  recursive: true'                                      + #13#10 +
    ''                                                       + #13#10 +
    'operation:'                                             + #13#10 +
    '  mode: both'                                           + #13#10 +
    ''                                                       + #13#10 +
    'sync:'                                                  + #13#10 +
    '  enabled: true'                                        + #13#10 +
    '  destination_folder: ' + SyncDest                      + #13#10 +
    '  mode: diff'                                           + #13#10 +
    ''                                                       + #13#10 +
    'parser:'                                                + #13#10 +
    '  scan_interval: 5'                                     + #13#10 +
    ''                                                       + #13#10 +
    'spec_check:'                                            + #13#10 +
    '  enabled: true'                                        + #13#10 +
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
  StationId: String;
begin
  StationId := BuildStationId;

  Result :=
    'Estação configurada:' + NewLine +
    Space + 'Station ID  : ' + StationId                                    + NewLine +
    Space + 'Modelo      : ' + UpperCase(Trim(PageEstacao.Values[0]))       + NewLine +
    Space + 'Máquina     : ' + UpperCase(Trim(PageEstacao.Values[1]))       + NewLine +
    Space + 'Linha       : ' + UpperCase(Trim(PageConfig.Values[0]))        + NewLine +
    Space + 'Pasta CSV   : ' + Trim(PageConfig.Values[1])                   + NewLine +
    Space + 'Banco       : ' + Trim(PageBanco.Values[0]) + ':' + Trim(PageBanco.Values[1]) + '/' + Trim(PageBanco.Values[2]) + NewLine +
    NewLine +
    'Ações que serão executadas:' + NewLine +
    Space + 'Copiar MES_Client.exe para C:\Utility\MES'                     + NewLine +
    Space + 'Gerar config.yaml para esta estação'                           + NewLine +
    Space + 'Registrar inicialização automática (Task Scheduler)'           + NewLine +
    Space + 'Criar atalho na Área de Trabalho';
end;
