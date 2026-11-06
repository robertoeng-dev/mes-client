; ==============================================================================
; MES_Client_Setup_Win7.iss  -  EDICAO WINDOWS 7 SP1
; Script Inno Setup - Instalador do Proteus Client 2.0 (estacoes de teste)
; Salcomp - Engenharia de Teste | Manaus
; ==============================================================================
; EDICAO WINDOWS 7 SP1 (Python 3.8.10, 32 bits - roda em Win7 32 e 64 bits).
;   Nao compile direto daqui: o build_win7.bat roda na pasta gerada por
;   win7\gerar_edicao_win7.py (padrao WINDOWS7_v2.0\src), onde este arquivo
;   fica em installer\ e os pre-requisitos em installer\prereqs\*.msu.
;   Saida: installer\Output\Proteus_Client_Setup_v2.0.0-win7.exe
;   Diferencas para a edicao Windows 10 (marcadas [WIN7] no codigo):
;     - confere KB2533623 (AddDllDirectory) - sem ele o Python 3.8 nao carrega
;     - instala o UCRT (KB2999226, embutido) se faltar ucrtbase.dll
;     - MinVersion 6.1sp1; arquivo e desinstalador com "win7" / "(Windows 7)"
;
; CLIENTE 2.0 = CADASTRO CENTRALIZADO. Estacao, linha, formato do log e padrao
; de arquivo vem do servidor (Proteus - Servidor de Gerenciamento). O
; instalador so grava:
;   - a conexao com o banco do DOMINIO (Non-Alpha: mes_nonalpha; Alpha: mes_alpha)
;   - a senha do role da estacao, no .env (nunca no config.yaml)
;   - opcionalmente a PRIMEIRA fonte deste PC (estacao + fonte + pasta). Sem
;     ela o cliente abre sozinho a tela FONTES DESTE PC no primeiro start.
;
; ATUALIZACAO DA v1.0.5: mesmo AppId, instala por cima em C:\Utility\MES. O
; config.yaml da v1.0.5 (formato antigo, com "station:") nao serve para a 2.0:
; ele, a fila offline e os offsets sao renomeados para *.v105.bak e um config
; novo e' gerado. Um config.yaml que ja' e' 2.0 e' preservado.
;
; Instalacao silenciosa (sem wizard), para escalar em varias estacoes:
;   Proteus_Client_Setup_v2.0.0-win7.exe /SILENT /DOMINIO=NONALPHA /DBPASS=<senha>
;       /STATION=CAIAPO-M13-FT /FONTE=FT /PASTA="D:\battData"
;   Opcionais (com padrao): /DBHOST=172.21.70.184 /DBPORT=5432
;       /DBNAME=mes_<dominio> /DBUSER=mes_client_<dominio> /SYNC=""
;   /DOMINIO aceita NONALPHA ou ALPHA. /DBPASS e' obrigatorio no silencioso.
;   Nunca grave a linha com /DBPASS em arquivo.
; ==============================================================================

#define AppName      "Proteus Client"
#define AppVersion   "2.0.0"
#define AppPublisher "Salcomp - Engenharia de Teste"
#define AppCopyright "Salcomp Manaus 2026"
#define InstallDir   "C:\Utility\MES"
; Nomes tecnicos mantidos da v1.0.5 (atualizacao por cima, tarefa e mutex)
#define ExeName      "MES_Client.exe"
#define TaskName     "MES_Client_Autostart"

#define Edicao     " (Windows 7)"
#define SufixoArq  "-win7"

; ==============================================================================
[Setup]
; Mesmo AppId da v1.0.5: a 2.0 atualiza a instalacao existente
AppId={{A3F2C1D0-9B4E-4F7A-8C3D-1E6B2A0F5D9C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}{#Edicao}
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
OutputBaseFilename=Proteus_Client_Setup_v{#AppVersion}{#SufixoArq}

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

; [WIN7] Windows 7 SP1 ou mais novo (o exe e' Python 3.8 32 bits)
MinVersion=6.1sp1

UninstallDisplayIcon={app}\{#ExeName}
UninstallDisplayName={#AppName}{#Edicao}

; ==============================================================================
[Languages]
Name: "ptBR"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

; ==============================================================================
[Messages]
ptBR.WelcomeLabel1=Bem-vindo ao instalador do [name]
ptBR.WelcomeLabel2=Este assistente instalara o [name/ver]{#Edicao} nesta estacao de teste.%n%nVoce vai precisar do dominio (Non-Alpha ou Alpha) e da senha do banco das estacoes. A estacao e a fonte de log podem ser vinculadas agora ou depois, na tela FONTES DESTE PC.%n%nClique em Avancar para continuar.%n%nBy Parente - Engenharia de Testes Manaus
ptBR.FinishedLabel=A instalacao do [name] foi concluida com sucesso.%n%nClique em Concluir para fechar este assistente.%n%nBy Parente - Engenharia de Testes Manaus

; ==============================================================================
[Files]
; EXE principal
Source: "..\dist\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Limites de especificacao
Source: "..\spec_limits.csv";        DestDir: "{app}"; Flags: ignoreversion

; Mapeamento de colunas CSV (editavel via tela MAPEAMENTO da UI)
Source: "..\column_mappings.json";   DestDir: "{app}"; Flags: ignoreversion

; Icone (para o atalho e desinstalador)
Source: "..\assets\app.ico";         DestDir: "{app}\assets"; Flags: ignoreversion

; [WIN7] Runtime C universal (UCRT) da Microsoft - so e' extraido e instalado
; se faltar ucrtbase.dll (ver PrepareToInstall). Nao vai para {app}.
Source: "prereqs\Windows6.1-KB2999226-x86.msu"; Flags: dontcopy
Source: "prereqs\Windows6.1-KB2999226-x64.msu"; Flags: dontcopy

; ==============================================================================
[InstallDelete]
; Atalho com o nome antigo (v1.0.5) - o novo se chama Proteus Client
Type: files; Name: "{commondesktop}\MES Client.lnk"

; ==============================================================================
[Icons]
; Atalho na area de trabalho de todos os usuarios
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"; Comment: "Proteus Client - coleta dos logs de teste para o MES"

; ==============================================================================
[Run]
; Inicia o cliente ao finalizar (opcional, usuario pode desmarcar)
Filename: "{app}\{#ExeName}"; Description: "Iniciar o {#AppName} agora"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"; Check: not UcrtPendente

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
  Paginas customizadas do wizard (Pascal Script)

  Todos os campos aceitam valor pela linha de comando (/NOME=valor). Em modo
  /SILENT as paginas nao aparecem e os valores usados sao exatamente os dos
  parametros (ou o padrao de cada campo); a validacao fica no PrepareToInstall.
  ============================================================================ }

var
  { Pagina 1: dominio (Non-Alpha / Alpha) - define banco e usuario padrao }
  PageDominio: TInputOptionWizardPage;

  { Pagina 2: conexao (host, porta, banco, usuario) }
  PageBanco: TInputQueryWizardPage;

  { Pagina 3: senha, em pagina propria. O TInputQueryWizardPage nao
    redimensiona a janela: com muitos campos a senha ficava fora da area
    visivel (problema real da v1.0.4). }
  PageSenha: TInputQueryWizardPage;

  { Pagina 4: primeira fonte deste PC (opcional) }
  PageFonte: TInputQueryWizardPage;

  { Ultimos valores sugeridos sozinhos: se o tecnico nao mexeu, trocar o
    dominio recalcula banco e usuario. }
  NomeSugerido: String;
  UserSugerido: String;

  { /DOMINIO= com valor desconhecido - recusado no PrepareToInstall }
  DominioInvalido: Boolean;

  { [WIN7] True quando o UCRT foi instalado agora e o Windows pediu reinicio:
    o cliente so' consegue abrir depois de reiniciar. }
  GUcrtPendente: Boolean;


{ --------------------------------------------------------------------------
  WIN7: Pre-requisitos do Python 3.8 no Windows 7 SP1
    KB2533623 - adiciona AddDllDirectory ao kernel32. Sem ele o Python 3.8
                nao carrega as proprias DLLs (_ctypes, _tkinter, psycopg2).
                Ja vem em qualquer Win7 com Windows Update; o pacote avulso
                foi substituido pelo KB3063858.
    KB2999226 - Universal C Runtime (ucrtbase.dll). Embutido neste instalador.
  -------------------------------------------------------------------------- }
function GetModuleHandle(lpModuleName: String): THandle;
  external 'GetModuleHandleW@kernel32.dll stdcall';
function GetProcAddress(hModule: THandle; lpProcName: AnsiString): THandle;
  external 'GetProcAddress@kernel32.dll stdcall';

function TemAddDllDirectory: Boolean;
begin
  Result := GetProcAddress(GetModuleHandle('kernel32.dll'), 'AddDllDirectory') <> 0;
end;

{ Instalador e cliente sao 32 bits: num Windows 64 bits o que conta e' o
  ucrtbase.dll de SysWOW64 - e' exatamente onde a constante sys aponta para
  um setup 32 bits (redirecionamento do WOW64). }
function TemUcrt: Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\ucrtbase.dll'));
end;

function UcrtPendente: Boolean;
begin
  Result := GUcrtPendente;
end;

function NeedRestart: Boolean;
begin
  Result := GUcrtPendente;
end;

{ Instala o KB2999226 com o wusa.exe do proprio Windows. Retorna '' se deu
  certo (ou reinicio pendente) e a mensagem de erro caso contrario. }
function InstalarUcrt: String;
var
  Msu, Wusa: String;
  ResultCode: Integer;
begin
  Result := '';
  if IsWin64 then begin
    Msu  := 'Windows6.1-KB2999226-x64.msu';
    { wusa 32 bits nao instala pacote x64 - usa o nativo de System32 }
    Wusa := ExpandConstant('{sysnative}\wusa.exe');
  end else begin
    Msu  := 'Windows6.1-KB2999226-x86.msu';
    Wusa := ExpandConstant('{sys}\wusa.exe');
  end;

  ExtractTemporaryFile(Msu);
  Log('Instalando UCRT: ' + Msu);
  WizardForm.StatusLabel.Caption := 'Instalando o Runtime C Universal do Windows (KB2999226)...';

  if not Exec(Wusa, '"' + ExpandConstant('{tmp}\' + Msu) + '" /quiet /norestart',
              '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
    Result := 'Nao foi possivel executar o wusa.exe para instalar o KB2999226.';
    Exit;
  end;
  Log('wusa.exe terminou com codigo ' + IntToStr(ResultCode));

  { 0 = instalado; 3010 = instalado, reinicio pendente;
    2359302 (0x240006) = ja instalado; -2145124329 (0x80240017) = nao se aplica }
  if TemUcrt then
    Exit;

  if ResultCode = 3010 then begin
    GUcrtPendente := True;
    Exit;
  end;

  if ResultCode = -2147023838 then
    Result := 'O servico Windows Update esta desativado nesta estacao (erro 0x80070422).' + #13#10 +
              'O wusa.exe precisa dele para instalar o KB2999226. Em services.msc, ' +
              'coloque "Windows Update" como Manual, rode o instalador de novo e ' +
              'depois volte a desativar se a TI exigir.'
  else
    Result := 'Falha ao instalar o Runtime C Universal (KB2999226), codigo ' +
              IntToStr(ResultCode) + '.' + #13#10 +
              'Instale o KB2999226 manualmente (arquivo .msu da pasta prereqs do ' +
              'pacote) e rode este instalador de novo.';
end;


{ --------------------------------------------------------------------------
  Param: le /NOME=valor da linha de comando, com padrao
  -------------------------------------------------------------------------- }
function Param(Nome, Padrao: String): String;
begin
  Result := ExpandConstant('{param:' + Nome + '|' + Padrao + '}');
end;


{ 'nonalpha' ou 'alpha', conforme a opcao marcada na pagina 1 }
function Dominio: String;
begin
  if PageDominio.SelectedValueIndex = 1 then
    Result := 'alpha'
  else
    Result := 'nonalpha';
end;

function DominioRotulo: String;
begin
  if Dominio = 'alpha' then Result := 'Alpha' else Result := 'Non-Alpha';
end;


{ --------------------------------------------------------------------------
  CodigoValido: mesma regra do cadastro (dominio mes_codigo do banco):
  so A-Z, 0-9 e "_" ou "-" entre eles, ate 40 caracteres. O texto ja chega
  em maiusculas.
  -------------------------------------------------------------------------- }
function CodigoValido(S: String): Boolean;
var
  I: Integer;
  C: Char;
  Separador: Boolean;
begin
  Result := False;
  if (Length(S) = 0) or (Length(S) > 40) then
    Exit;
  Separador := True;   { nao pode comecar com separador }
  for I := 1 to Length(S) do begin
    C := S[I];
    if ((C >= 'A') and (C <= 'Z')) or ((C >= '0') and (C <= '9')) then
      Separador := False
    else if (C = '_') or (C = '-') then begin
      if Separador then
        Exit;          { dois separadores seguidos, ou no comeco }
      Separador := True;
    end else
      Exit;
  end;
  Result := not Separador;  { nem terminar com separador }
end;


{ Valor YAML entre aspas simples: barras invertidas ficam literais (pastas
  do Windows e UNC) e a aspa simples e' dobrada. }
function YamlStr(S: String): String;
begin
  StringChangeEx(S, '''', '''''', True);
  Result := '''' + S + '''';
end;


{ --------------------------------------------------------------------------
  Validacao da primeira fonte - usada pelo wizard e pelo silencioso.
  Tudo vazio = vincular depois. Retorna '' se ok.
  -------------------------------------------------------------------------- }
function ErroFonte: String;
var
  Estacao, Fonte, Pasta: String;
begin
  Result := '';
  Estacao := UpperCase(Trim(PageFonte.Values[0]));
  Fonte   := UpperCase(Trim(PageFonte.Values[1]));
  Pasta   := Trim(PageFonte.Values[2]);

  if (Estacao = '') and (Fonte = '') then
    Exit;    { vincular depois, pela tela FONTES DESTE PC }

  if not CodigoValido(Estacao) then
    Result := 'Codigo da estacao invalido: "' + Estacao + '".' + #13#10 +
              'Use o codigo exatamente como cadastrado no servidor (ex: CAIAPO-M13-FT).'
  else if not CodigoValido(Fonte) then
    Result := 'Codigo da fonte invalido: "' + Fonte + '" (ex: FT, OCV, AOI).'
  else if Pasta = '' then
    Result := 'Informe a pasta onde o equipamento grava os logs desta fonte.';
end;


{ --------------------------------------------------------------------------
  InitializeWizard: executado uma vez ao abrir o wizard (tambem no /SILENT)
  -------------------------------------------------------------------------- }
procedure InitializeWizard;
var
  ParamDom: String;
begin
  { --- PAGINA 1: Dominio --- }
  PageDominio := CreateInputOptionPage(
    wpWelcome,
    'Domínio da estação',
    'Em qual banco esta estação grava',
    'Non-Alpha e Alpha são bancos separados: uma estação pertence a um domínio só, ' +
    'e a senha de um não abre o outro.',
    True, False);
  PageDominio.Add('Non-Alpha  (banco mes_nonalpha)');
  PageDominio.Add('Alpha  (banco mes_alpha)');

  ParamDom := UpperCase(Trim(Param('DOMINIO', 'NONALPHA')));
  StringChangeEx(ParamDom, '-', '', True);
  DominioInvalido := (ParamDom <> 'NONALPHA') and (ParamDom <> 'ALPHA');
  if ParamDom = 'ALPHA' then
    PageDominio.SelectedValueIndex := 1
  else
    PageDominio.SelectedValueIndex := 0;

  { --- PAGINA 2: Banco de Dados --- }
  PageBanco := CreateInputQueryPage(
    PageDominio.ID,
    'Conexão com o banco de dados',
    'PostgreSQL do servidor Salcomp',
    'Em produção, mantenha os valores padrão. Altere somente se o servidor mudou ' +
    'ou para homologação.');

  PageBanco.Add('Host do servidor (IP ou nome):', False);
  PageBanco.Add('Porta PostgreSQL:', False);
  PageBanco.Add('Nome do banco:', False);
  PageBanco.Add('Usuário do banco (role das estações):', False);

  { Host com padrao: so existe um servidor (172.21.70.184), endereco interno ja
    documentado no repositorio. A SENHA nunca tem padrao: este .iss e' publico
    no GitHub. O tecnico digita na instalacao ou passa /DBPASS no silencioso. }
  NomeSugerido := 'mes_' + Dominio;
  UserSugerido := 'mes_client_' + Dominio;
  PageBanco.Values[0] := Param('DBHOST', '172.21.70.184');
  PageBanco.Values[1] := Param('DBPORT', '5432');
  PageBanco.Values[2] := Param('DBNAME', NomeSugerido);
  PageBanco.Values[3] := Param('DBUSER', UserSugerido);

  { --- PAGINA 3: Senha --- }
  PageSenha := CreateInputQueryPage(
    PageBanco.ID,
    'Senha do banco de dados',
    'Senha do role das estações deste domínio',
    'A senha é gravada apenas no arquivo .env desta estação, nunca no config.yaml. ' +
    'Peça à engenharia; não anote em papel nem em arquivo.');
  PageSenha.Add('Senha do banco:', True);  { True = oculta a senha }
  PageSenha.Values[0] := Param('DBPASS', '');

  { --- PAGINA 4: Primeira fonte (opcional) --- }
  PageFonte := CreateInputQueryPage(
    PageSenha.ID,
    'Fonte de log deste PC (opcional)',
    'Qual log do equipamento este PC envia ao banco',
    'Use os códigos cadastrados no servidor de gerenciamento. Deixe estação e fonte ' +
    'vazias para vincular depois pela tela FONTES DESTE PC (abre sozinha no primeiro start). ' +
    'O vínculo é confirmado pelo servidor quando o cliente abre.');
  PageFonte.Add('Código da estação (ex: CAIAPO-M13-FT):', False);
  PageFonte.Add('Fonte (ex: FT, OCV, AOI):', False);
  PageFonte.Add('Pasta onde o equipamento grava os logs (ex: D:\battData):', False);
  PageFonte.Add('Cópia dos arquivos para a rede (UNC, opcional; vazio = não copiar):', False);
  PageFonte.Values[0] := UpperCase(Param('STATION', ''));
  PageFonte.Values[1] := UpperCase(Param('FONTE', ''));
  PageFonte.Values[2] := Param('PASTA', '');
  PageFonte.Values[3] := Param('SYNC', '');
end;


{ --------------------------------------------------------------------------
  NextButtonClick: validacao ao clicar em Avancar em cada pagina
  -------------------------------------------------------------------------- }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Erro: String;
begin
  Result := True;

  if CurPageID = PageDominio.ID then begin
    { Recalcula banco e usuario - so se o tecnico nao alterou a sugestao }
    if (Trim(PageBanco.Values[2]) = '') or (PageBanco.Values[2] = NomeSugerido) then
      PageBanco.Values[2] := 'mes_' + Dominio;
    if (Trim(PageBanco.Values[3]) = '') or (PageBanco.Values[3] = UserSugerido) then
      PageBanco.Values[3] := 'mes_client_' + Dominio;
    NomeSugerido := 'mes_' + Dominio;
    UserSugerido := 'mes_client_' + Dominio;
  end;

  if CurPageID = PageBanco.ID then begin
    if (Trim(PageBanco.Values[0]) = '') or (Trim(PageBanco.Values[1]) = '') or
       (Trim(PageBanco.Values[2]) = '') or (Trim(PageBanco.Values[3]) = '') then begin
      MsgBox('Preencha host, porta, banco e usuário.' + #13#10 +
             'Peça os dados à engenharia se não souber.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if StrToIntDef(Trim(PageBanco.Values[1]), 0) <= 0 then begin
      MsgBox('Porta inválida: ' + PageBanco.Values[1], mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;

  if CurPageID = PageSenha.ID then begin
    if Trim(PageSenha.Values[0]) = '' then begin
      MsgBox('Informe a senha do banco.' + #13#10 +
             'Ela será gravada no arquivo .env da estação, nunca no config.yaml.',
             mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;

  if CurPageID = PageFonte.ID then begin
    PageFonte.Values[0] := UpperCase(Trim(PageFonte.Values[0]));
    PageFonte.Values[1] := UpperCase(Trim(PageFonte.Values[1]));
    Erro := ErroFonte;
    if Erro <> '' then begin
      MsgBox(Erro, mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;


{ --------------------------------------------------------------------------
  PararCliente: numa atualizacao o cliente esta' aberto na bandeja e o exe
  fica travado. Primeiro encerra a tarefa agendada (senao o RestartOnFailure
  dela reabre o cliente em 1 minuto), depois o processo.
  -------------------------------------------------------------------------- }
procedure PararCliente;
var
  ResultCode: Integer;
begin
  Exec('schtasks.exe', '/End /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM {#ExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;


{ --------------------------------------------------------------------------
  PrepareToInstall: ultima chance de abortar. Em modo silencioso as paginas
  nao rodam NextButtonClick, entao os campos obrigatorios sao conferidos
  aqui. Retornar texto nao vazio cancela a instalacao mostrando a mensagem.
  -------------------------------------------------------------------------- }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if WizardSilent then begin
    PageFonte.Values[0] := UpperCase(Trim(PageFonte.Values[0]));
    PageFonte.Values[1] := UpperCase(Trim(PageFonte.Values[1]));
    if DominioInvalido then
      Result := 'Modo silencioso: /DOMINIO deve ser NONALPHA ou ALPHA.'
    else if Trim(PageSenha.Values[0]) = '' then
      Result := 'Modo silencioso: informe /DBPASS=<senha do banco>.'
    else if StrToIntDef(Trim(PageBanco.Values[1]), 0) <= 0 then
      Result := 'Modo silencioso: /DBPORT invalido.'
    else
      Result := ErroFonte;
    if Result <> '' then
      Exit;
  end;

  { [WIN7] Pre-requisitos, no wizard e no silencioso - so depois dos
    parametros validados, para nao instalar atualizacao do Windows a toa }
  if not TemAddDllDirectory then begin
    Result := 'Falta a atualizacao KB2533623 do Windows 7 (incluida no KB3063858).' + #13#10 +
              'Sem ela o Proteus Client nao abre. Instale pelo Windows Update/WSUS ' +
              '(ou o .msu do KB3063858 para esta arquitetura), reinicie e rode ' +
              'este instalador de novo.';
    Exit;
  end;

  if not TemUcrt then begin
    Result := InstalarUcrt;
    if Result <> '' then
      Exit;
  end;

  PararCliente;
end;


function BoolStr(B: Boolean): String;
begin
  if B then Result := 'true' else Result := 'false';
end;


{ True se o config.yaml existente ja' e' do formato 2.0 (cadastro central).
  O da v1.0.5 tem "station:" e nao tem "vinculos:"/"cliente:". }
function ConfigEh20(Caminho: String): Boolean;
var
  S: AnsiString;
begin
  Result := False;
  if LoadStringFromFile(Caminho, S) then
    Result := (Pos('vinculos:', S) > 0) or (Pos('cliente:', S) > 0);
end;


{ Guarda um arquivo da v1.0.5 como <nome>.v105.bak (substitui bak anterior) }
procedure GuardarV105(Nome: String);
var
  Origem, Destino: String;
begin
  Origem  := ExpandConstant('{app}\' + Nome);
  Destino := Origem + '.v105.bak';
  if not FileExists(Origem) then
    Exit;
  DeleteFile(Destino);
  if RenameFile(Origem, Destino) then
    Log('v1.0.5: ' + Nome + ' -> ' + Nome + '.v105.bak')
  else
    Log('v1.0.5: nao consegui renomear ' + Nome);
end;


{ --------------------------------------------------------------------------
  GenerateConfig: grava o .env e o config.yaml na pasta de instalacao

  1. A SENHA vai para o .env, nunca para o config.yaml. O config guarda so' o
     placeholder da variavel MES_DB_PASSWORD, que o config/loader.py resolve.
     ATENCAO: nao escreva a sintaxe completa do placeholder dentro de um
     comentario Pascal - a chave de fechamento encerraria o comentario.
  2. Um config.yaml 2.0 existente e' PRESERVADO (vinculos feitos na tela
     FONTES DESTE PC, ajustes a mao). O .env e' sempre reescrito.
  3. Um config.yaml da v1.0.5 e' guardado como .v105.bak, junto com a fila
     offline e os offsets (formato e banco antigos), e um config 2.0 e' gerado.
  -------------------------------------------------------------------------- }
procedure GenerateConfig;
var
  ConfigPath, EnvPath, Content, Vinculos: String;
  Estacao, Fonte, Pasta, SyncDest, OpMode: String;
begin
  ConfigPath := ExpandConstant('{app}\config.yaml');
  EnvPath    := ExpandConstant('{app}\.env');

  { --- .env: sempre reescrito, e' onde a senha do banco mora --- }
  SaveStringToFile(EnvPath, 'MES_DB_PASSWORD=' + Trim(PageSenha.Values[0]) + #13#10, False);

  if FileExists(ConfigPath) then begin
    if ConfigEh20(ConfigPath) then
      Exit;     { estacao 2.0 ja' configurada: preserva }
    GuardarV105('config.yaml');
    GuardarV105('offline_queue.jsonl');
    GuardarV105('offsets.json');
  end;

  Estacao  := UpperCase(Trim(PageFonte.Values[0]));
  Fonte    := UpperCase(Trim(PageFonte.Values[1]));
  Pasta    := Trim(PageFonte.Values[2]);
  SyncDest := Trim(PageFonte.Values[3]);

  if Estacao = '' then begin
    Vinculos := 'vinculos: []                   # vazio: o cliente abre a tela FONTES DESTE PC' + #13#10;
    SyncDest := '';
  end else
    Vinculos :=
      'vinculos:'                                            + #13#10 +
      '  - estacao: ' + Estacao                              + #13#10 +
      '    fonte: '   + Fonte                                + #13#10 +
      '    pasta: '   + YamlStr(Pasta)                       + #13#10 +
      '    sync_destino: ' + YamlStr(SyncDest)               + #13#10;

  { Sem copia para a rede o modo e' "database"; com copia, "both" }
  if SyncDest <> '' then OpMode := 'both' else OpMode := 'database';

  Content :=
    '# config.yaml - Proteus Client {#AppVersion} (gerado pelo instalador)'  + #13#10 +
    '# Dominio: ' + DominioRotulo + '. Senha no arquivo .env (nunca aqui).'   + #13#10 +
    '# Fontes deste PC: tela FONTES DESTE PC (senha de engenharia).'          + #13#10 +
    ''                                                       + #13#10 +
    'database:'                                              + #13#10 +
    '  enabled: true'                                        + #13#10 +
    '  host: '     + Trim(PageBanco.Values[0])               + #13#10 +
    '  port: '     + Trim(PageBanco.Values[1])               + #13#10 +
    '  name: '     + Trim(PageBanco.Values[2])               + #13#10 +
    '  user: '     + Trim(PageBanco.Values[3])               + #13#10 +
    '  password: ${MES_DB_PASSWORD}'                         + #13#10 +
    ''                                                       + #13#10 +
    'cliente:'                                               + #13#10 +
    '  host_id: ""                    # vazio = nome do PC'  + #13#10 +
    ''                                                       + #13#10 +
    Vinculos                                                 +
    ''                                                       + #13#10 +
    'operation:'                                             + #13#10 +
    '  mode: ' + OpMode                                      + #13#10 +
    ''                                                       + #13#10 +
    'sync:'                                                  + #13#10 +
    '  destination_folder: ""'                               + #13#10 +
    '  mode: diff'                                           + #13#10 +
    ''                                                       + #13#10 +
    'parser:'                                                + #13#10 +
    '  scan_interval: 5'                                     + #13#10 +
    ''                                                       + #13#10 +
    'spec_check:'                                            + #13#10 +
    '  enabled: false'                                       + #13#10 +
    '  file: spec_limits.csv'                                + #13#10 +
    ''                                                       + #13#10 +
    'auth:'                                                  + #13#10 +
    '  operador_password: ""'                                + #13#10 +
    '  engenharia_password: "admin"'                         + #13#10;

  SaveStringToFile(ConfigPath, Content, False);
end;


{ --------------------------------------------------------------------------
  RegisterTaskScheduler: cria tarefa de auto-start via schtasks.exe (XML)
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

  Exec('schtasks.exe',
       '/Create /TN "{#TaskName}" /XML "' + XmlPath + '" /F',
       '',
       SW_HIDE,
       ewWaitUntilTerminated,
       ResultCode);

  { Sem a tarefa o cliente nao volta sozinho apos reiniciar - avisa em vez de
    terminar a instalacao como se estivesse tudo certo }
  Log('schtasks /Create terminou com codigo ' + IntToStr(ResultCode));
  if ResultCode <> 0 then
    SuppressibleMsgBox('Nao foi possivel criar a tarefa de inicio automatico ' +
      '(schtasks codigo ' + IntToStr(ResultCode) + ').' + #13#10 +
      'O Proteus Client foi instalado, mas nao vai abrir sozinho apos reiniciar. ' +
      'Avise a engenharia.', mbError, MB_OK, IDOK);
end;


{ --------------------------------------------------------------------------
  CurStepChanged: ssPostInstall = apos copiar todos os arquivos
  -------------------------------------------------------------------------- }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    ForceDirectories(ExpandConstant('{app}\logs'));
    ForceDirectories(ExpandConstant('{app}\state'));
    ForceDirectories(ExpandConstant('{app}\data'));
    GenerateConfig;
    RegisterTaskScheduler;
  end;
end;


{ --------------------------------------------------------------------------
  CurUninstallStepChanged: usUninstall = logo antes de remover os arquivos
  -------------------------------------------------------------------------- }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    Exec('schtasks.exe', '/End /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM {#ExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('schtasks.exe', '/Delete /TN "{#TaskName}" /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;


{ --------------------------------------------------------------------------
  UpdateReadyMemo: texto da pagina "Pronto para instalar"
  -------------------------------------------------------------------------- }
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  ConfigPath, ConfigAcao, FonteTxt, SyncTxt: String;
begin
  ConfigPath := ExpandConstant('{app}\config.yaml');
  if not FileExists(ConfigPath) then
    ConfigAcao := 'Gerar config.yaml 2.0 para esta estação'
  else if ConfigEh20(ConfigPath) then
    ConfigAcao := 'Preservar o config.yaml 2.0 existente (fonte acima ignorada; banco e senha: só o .env muda)'
  else
    ConfigAcao := 'Atualizar da v1.0.5: guardar config.yaml, fila e offsets como *.v105.bak e gerar config 2.0';

  if Trim(PageFonte.Values[0]) = '' then
    FonteTxt := '(vincular depois, na tela FONTES DESTE PC)'
  else
    FonteTxt := UpperCase(Trim(PageFonte.Values[0])) + ' / ' + UpperCase(Trim(PageFonte.Values[1])) +
                '  <-  ' + Trim(PageFonte.Values[2]);

  if Trim(PageFonte.Values[3]) = '' then
    SyncTxt := '(desligada)'
  else
    SyncTxt := Trim(PageFonte.Values[3]);

  Result :=
    'Estação:' + NewLine +
    Space + 'Domínio     : ' + DominioRotulo                                      + NewLine +
    Space + 'Banco       : ' + Trim(PageBanco.Values[0]) + ':' + Trim(PageBanco.Values[1]) +
                               '/' + Trim(PageBanco.Values[2]) + '  (usuário ' + Trim(PageBanco.Values[3]) + ')' + NewLine +
    Space + 'Fonte       : ' + FonteTxt                                           + NewLine +
    Space + 'Cópia rede  : ' + SyncTxt                                            + NewLine +
    NewLine +
    'Ações que serão executadas:' + NewLine +
    Space + 'Encerrar o cliente, se estiver aberto'                               + NewLine +
    Space + 'Copiar {#ExeName} para {#InstallDir}'                                + NewLine +
    Space + ConfigAcao                                                            + NewLine +
    Space + 'Gravar a senha do banco no arquivo .env'                             + NewLine +
    Space + 'Registrar inicialização automática (Task Scheduler)'                 + NewLine +
    Space + 'Criar atalho "{#AppName}" na Área de Trabalho';
end;
