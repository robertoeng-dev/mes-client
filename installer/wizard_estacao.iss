{ ==============================================================================
  wizard_estacao.iss - Proteus Client 2.0.3 (incluido pelos dois instaladores)

  Item 47: estacao escolhida no wizard a partir do cadastro do servidor.
    Planta -> Secao -> Linha -> Estacao/Fonte, so' as ATIVAS e LIVRES. As
    ocupadas por outro PC ficam ocultas (so' a contagem aparece). Ao avancar,
    o slot e' reservado na hora pela funcao mes_vincular_estacao do banco (a
    mesma do cliente): se outro PC pegou antes, o banco recusa. Liberar um
    slot so' pelo painel Proteus (Engenharia/Administrador).
  Item 44: numa ATUALIZACAO de uma estacao 2.0, host/porta/banco/usuario
    (e set_role) vem do config.yaml atual e a senha do .env, e a conexao e'
    testada antes de instalar.

  O Inno Setup nao fala com o PostgreSQL: o wizard extrai o MES_Client.exe
  novo para a pasta temporaria do Setup e o chama em "--wizard catalogo|vincular" (ver
  system\wizard_helper.py). A senha vai num arquivo da pasta temporaria do Setup que o exe apaga
  ao ler - nunca na linha de comando. Sem rede, sem servidor ou sem os
  pre-requisitos do Win7, o wizard volta ao modo manual (como na 2.0.2).

  Precisa, ANTES do #include: PageBanco, PageSenha, PageFonte, Param,
  CodigoValido e a funcao PodeRodarAjudante (cada edicao define a sua).
  ============================================================================== }

type
  TFonteCat = record
    Planta, PlantaNome, Secao, SecaoNome, Linha, LinhaNome: String;
    Estacao, EstDesc, Tipo, Modelo, Fonte, Formato, Padrao, Status, Host: String;
  end;

var
  Cat: array of TFonteCat;
  CatOK: Boolean;              { catalogo lido do servidor nesta instalacao }
  CatHost: String;             { nome deste PC como o banco o ve }
  CatErro: String;
  ExeExtraido: Boolean;
  SlotReservado: String;       { estacao reservada para este PC nesta instalacao }

  { Item 44: valores do config.yaml 2.0 existente }
  AtualizacaoCfg20: Boolean;
  CfgHost, CfgPort, CfgName, CfgUser, CfgSetRole, CfgSenha: String;

  PageEstacao: TWizardPage;
  PageEspera: TOutputProgressWizardPage;
  CbPlanta, CbSecao, CbLinha, CbEstacao: TNewComboBox;
  LblDetalhe, LblPC: TNewStaticText;
  IdxEstacao: array of Integer;  { item do CbEstacao -> indice em Cat (-1 = depois) }


{ ---------------------------------------------------------------- utilidades }

{ N-esimo campo (a partir de 0) de uma linha separada por | }
function CampoN(S: String; N: Integer): String;
var
  I, P: Integer;
begin
  Result := '';
  for I := 1 to N do begin
    P := Pos('|', S);
    if P = 0 then
      Exit;
    Delete(S, 1, P);
  end;
  P := Pos('|', S);
  if P = 0 then Result := S else Result := Copy(S, 1, P - 1);
end;

function Rotulo(Cod, Nome: String): String;
begin
  if (Nome = '') or (UpperCase(Nome) = UpperCase(Cod)) then
    Result := Cod
  else
    Result := Cod + ' - ' + Nome;
end;

{ Codigo do item escolhido ("MAO - Manaus" -> "MAO") }
function CodDe(Cb: TNewComboBox): String;
var
  S: String;
  P: Integer;
begin
  Result := '';
  if Cb.ItemIndex < 0 then
    Exit;
  S := Cb.Items[Cb.ItemIndex];
  P := Pos(' ', S);
  if P > 0 then Result := Copy(S, 1, P - 1) else Result := S;
end;

procedure AddUnico(Cb: TNewComboBox; Item: String);
begin
  if Cb.Items.IndexOf(Item) < 0 then
    Cb.Items.Add(Item);
end;

{ Valor YAML de uma linha "chave: valor" (aspas, comentario) }
function ValorYaml(V: String): String;
var
  P: Integer;
  Q: String;
begin
  V := Trim(V);
  Result := V;
  if V = '' then
    Exit;
  Q := Copy(V, 1, 1);
  if (Q = '''') or (Q = '"') then begin
    Delete(V, 1, 1);
    if Q = '''' then
      StringChangeEx(V, '''''', #1, True);   { aspa dobrada = aspa literal }
    P := Pos(Q, V);
    if P > 0 then
      V := Copy(V, 1, P - 1);
    StringChangeEx(V, #1, '''', True);
    Result := V;
  end else begin
    P := Pos(' #', V);
    if P > 0 then
      V := Copy(V, 1, P - 1);
    Result := Trim(V);
  end;
end;

{ Padrao do nome do PC: <LINHA>-<MAQUINA>, o codigo da estacao sem a sigla }
function NomePcSugerido(Estacao: String): String;
var
  I: Integer;
begin
  Result := Estacao;
  for I := Length(Estacao) downto 1 do
    if Estacao[I] = '-' then begin
      Result := Copy(Estacao, 1, I - 1);
      Exit;
    end;
end;

function NomeGenerico(H: String): Boolean;
begin
  H := UpperCase(H);
  Result := (H = '') or (H = 'PC') or (H = 'ADMIN') or (H = 'USER') or
            (Copy(H, 1, 8) = 'DESKTOP-') or (Copy(H, 1, 4) = 'WIN-') or
            (Copy(H, 1, 7) = 'LAPTOP-') or
            ((Length(H) > 3) and (Copy(H, Length(H) - 2, 3) = '-PC'));
end;


{ ------------------------------------------------- item 44: config existente }

procedure LerConfigAtual;
var
  L: TArrayOfString;
  I, P: Integer;
  S, T, K, V, Secao: String;
begin
  AtualizacaoCfg20 := False;
  CfgHost := ''; CfgPort := ''; CfgName := ''; CfgUser := ''; CfgSetRole := ''; CfgSenha := '';
  if not LoadStringsFromFile('{#InstallDir}\config.yaml', L) then
    Exit;
  Secao := '';
  for I := 0 to GetArrayLength(L) - 1 do begin
    S := L[I];
    T := Trim(S);
    if (T = '') or (Copy(T, 1, 1) = '#') then
      Continue;
    P := Pos(':', T);
    if (Copy(S, 1, 1) <> ' ') and (Copy(S, 1, 1) <> '-') then begin
      if P > 0 then
        Secao := LowerCase(Copy(T, 1, P - 1));
      if (Secao = 'vinculos') or (Secao = 'cliente') then
        AtualizacaoCfg20 := True;
      Continue;
    end;
    if (Secao <> 'database') or (P = 0) then
      Continue;
    K := LowerCase(Trim(Copy(T, 1, P - 1)));
    V := ValorYaml(Copy(T, P + 1, Length(T)));
    if K = 'host' then CfgHost := V
    else if K = 'port' then CfgPort := V
    else if K = 'name' then CfgName := V
    else if K = 'user' then CfgUser := V
    else if K = 'set_role' then CfgSetRole := V;
  end;

  { config da v1.0.5 tambem tem "database:", mas aponta para o banco antigo }
  if not AtualizacaoCfg20 then begin
    CfgHost := ''; CfgPort := ''; CfgName := ''; CfgUser := ''; CfgSetRole := '';
    Exit;
  end;

  if LoadStringsFromFile('{#InstallDir}\.env', L) then
    for I := 0 to GetArrayLength(L) - 1 do
      if Copy(Trim(L[I]), 1, 16) = 'MES_DB_PASSWORD=' then
        CfgSenha := Copy(Trim(L[I]), 17, Length(L[I]));
  Log('Atualizacao de estacao 2.0: banco ' + CfgName + ' / usuario ' + CfgUser + ' lidos do config.yaml');
end;

function ValorOu(V, Padrao: String): String;
begin
  if Trim(V) <> '' then Result := V else Result := Padrao;
end;


{ ------------------------------------------------ chamada do exe (ajudante) }

function RodarAjudante(Acao, Estacao: String; var Linhas: TArrayOfString): Boolean;
var
  Ent: TArrayOfString;
  EntPath, SaiPath, Params: String;
  RC: Integer;
begin
  Result := False;
  SetArrayLength(Linhas, 0);
  if not PodeRodarAjudante then
    Exit;
  if not ExeExtraido then begin
    try
      ExtractTemporaryFile('{#ExeName}');
      ExeExtraido := True;
    except
      Log('wizard: nao consegui extrair o exe: ' + GetExceptionMessage);
      Exit;
    end;
  end;
  EntPath := ExpandConstant('{tmp}\wiz_entrada.txt');
  SaiPath := ExpandConstant('{tmp}\wiz_saida.txt');
  DeleteFile(SaiPath);
  SetArrayLength(Ent, 6);
  Ent[0] := 'host=' + Trim(PageBanco.Values[0]);
  Ent[1] := 'port=' + Trim(PageBanco.Values[1]);
  Ent[2] := 'name=' + Trim(PageBanco.Values[2]);
  Ent[3] := 'user=' + Trim(PageBanco.Values[3]);
  Ent[4] := 'password=' + Trim(PageSenha.Values[0]);
  Ent[5] := 'set_role=' + CfgSetRole;
  if not SaveStringsToUTF8File(EntPath, Ent, False) then
    Exit;
  Params := '--wizard ' + Acao + ' "' + EntPath + '" "' + SaiPath + '"';
  if Estacao <> '' then
    Params := Params + ' "' + Estacao + '"';
  if not Exec(ExpandConstant('{tmp}\{#ExeName}'), Params, ExpandConstant('{tmp}'),
              SW_HIDE, ewWaitUntilTerminated, RC) then begin
    DeleteFile(EntPath);
    Log('wizard: nao consegui executar o exe (' + Acao + ')');
    Exit;
  end;
  DeleteFile(EntPath);   { o exe ja apaga ao ler; garantia }
  Log('wizard: ' + Acao + ' terminou com codigo ' + IntToStr(RC));
  Result := LoadStringsFromFile(SaiPath, Linhas) and (GetArrayLength(Linhas) > 0);
  DeleteFile(SaiPath);
end;

procedure CarregarCatalogo;
var
  L: TArrayOfString;
  I, N: Integer;
  Ok: Boolean;
begin
  CatOK := False;
  CatErro := '';
  SetArrayLength(Cat, 0);
  if not PodeRodarAjudante then begin
    CatErro := 'Os pre-requisitos do Windows 7 (KB2999226) ainda nao estao instalados neste PC, ' +
               'entao o cadastro do servidor nao pode ser consultado agora.';
    Exit;
  end;
  PageEspera.SetText('Consultando o servidor Proteus...', 'Lendo as estacoes cadastradas e testando a senha.');
  PageEspera.Show;
  try
    Ok := RodarAjudante('catalogo', '', L);
  finally
    PageEspera.Hide;
  end;
  if not Ok then begin
    CatErro := 'O Proteus Client nao conseguiu rodar neste PC para consultar o servidor.';
    Exit;
  end;
  if CampoN(L[0], 0) <> 'OK' then begin
    CatErro := CampoN(L[0], 1);
    Exit;
  end;
  CatHost := CampoN(L[0], 1);
  N := 0;
  for I := 1 to GetArrayLength(L) - 1 do
    if CampoN(L[I], 0) = 'F' then begin
      SetArrayLength(Cat, N + 1);
      Cat[N].Planta     := CampoN(L[I], 1);
      Cat[N].PlantaNome := CampoN(L[I], 2);
      Cat[N].Secao      := CampoN(L[I], 3);
      Cat[N].SecaoNome  := CampoN(L[I], 4);
      Cat[N].Linha      := CampoN(L[I], 5);
      Cat[N].LinhaNome  := CampoN(L[I], 6);
      Cat[N].Estacao    := CampoN(L[I], 7);
      Cat[N].EstDesc    := CampoN(L[I], 8);
      Cat[N].Tipo       := CampoN(L[I], 9);
      Cat[N].Modelo     := CampoN(L[I], 10);
      Cat[N].Fonte      := CampoN(L[I], 11);
      Cat[N].Formato    := CampoN(L[I], 12);
      Cat[N].Padrao     := CampoN(L[I], 13);
      Cat[N].Status     := CampoN(L[I], 14);
      Cat[N].Host       := CampoN(L[I], 15);
      N := N + 1;
    end;
  CatOK := True;
  Log('wizard: catalogo com ' + IntToStr(N) + ' fonte(s) ativa(s); PC = ' + CatHost);
end;


{ ------------------------------------------------------ listas em cascata }

procedure AtualizarDetalhe;
var
  I, J, Ocupadas: Integer;
  Txt, PcTxt, Sug: String;
begin
  Ocupadas := 0;
  for J := 0 to GetArrayLength(Cat) - 1 do
    if (Cat[J].Planta = CodDe(CbPlanta)) and (Cat[J].Secao = CodDe(CbSecao)) and
       (Cat[J].Linha = CodDe(CbLinha)) and (Cat[J].Status = 'OCUPADA') then
      Ocupadas := Ocupadas + 1;

  Txt := '';
  Sug := '';
  if (CbEstacao.ItemIndex >= 0) and (CbEstacao.ItemIndex < GetArrayLength(IdxEstacao)) then
    I := IdxEstacao[CbEstacao.ItemIndex]
  else
    I := -1;
  if I >= 0 then begin
    Txt := 'Tipo: ' + Cat[I].Tipo + '    Modelo atual: ' + ValorOu(Cat[I].Modelo, '(nenhum)') +
           '    Formato: ' + Cat[I].Formato + '    Arquivos: ' + Cat[I].Padrao;
    if Cat[I].EstDesc <> '' then
      Txt := Txt + #13#10 + Cat[I].EstDesc;
    Sug := NomePcSugerido(Cat[I].Estacao);
  end else if CbEstacao.Items.Count <= 1 then
    Txt := 'Nenhuma estacao livre nesta linha. Cadastre uma nova no painel Proteus ' +
           '(mesma linha) ou peca a liberacao do vinculo da antiga.';
  if Ocupadas > 0 then
    Txt := Txt + #13#10 + IntToStr(Ocupadas) + ' estacao(oes) desta linha ja estao em outro PC (ocultas). ' +
           'Para trocar de PC, libere o vinculo no painel Proteus.';
  LblDetalhe.Caption := Txt;

  PcTxt := 'Nome deste PC: ' + CatHost;
  LblPC.Font.Color := clWindowText;
  if (Sug <> '') and (UpperCase(CatHost) <> UpperCase(Sug)) then begin
    PcTxt := PcTxt + '   (padrao: ' + Copy(Sug, 1, 15) + ')' + #13#10 +
             'Renomeie o PC para ' + Copy(Sug, 1, 15) + ' antes da producao: o vinculo fica preso ao nome do PC ' +
             '(no maximo 15 caracteres; exige reiniciar).';
    LblPC.Font.Color := $000080C0 { laranja escuro };
  end else if (Sug = '') and NomeGenerico(CatHost) then begin
    PcTxt := PcTxt + #13#10 + 'Nome generico: use o padrao <LINHA>-<MAQUINA> (ex.: CAIAPO-M13) ' +
             'para nao confundir o vinculo com outro PC.';
    LblPC.Font.Color := $000080C0;
  end;
  LblPC.Caption := PcTxt;
end;

procedure PreencherEstacoes;
var
  J, N, Escolher: Integer;
  S: String;
begin
  CbEstacao.Items.Clear;
  SetArrayLength(IdxEstacao, 1);
  IdxEstacao[0] := -1;
  CbEstacao.Items.Add('(vincular depois, na tela FONTES DESTE PC)');
  Escolher := 0;
  for J := 0 to GetArrayLength(Cat) - 1 do
    if (Cat[J].Planta = CodDe(CbPlanta)) and (Cat[J].Secao = CodDe(CbSecao)) and
       (Cat[J].Linha = CodDe(CbLinha)) and (Cat[J].Status <> 'OCUPADA') then begin
      S := Cat[J].Estacao + ' / ' + Cat[J].Fonte;
      if Cat[J].Status = 'ESTE_PC' then
        S := S + '   (ja vinculada a este PC)';
      CbEstacao.Items.Add(S);
      N := GetArrayLength(IdxEstacao);
      SetArrayLength(IdxEstacao, N + 1);
      IdxEstacao[N] := J;
      { pre-seleciona: a estacao deste PC (reinstalacao) ou a do /STATION= }
      if (Cat[J].Status = 'ESTE_PC') or
         ((Escolher = 0) and (Cat[J].Estacao = UpperCase(Trim(Param('STATION', ''))))) then
        Escolher := N;
    end;
  if (Escolher = 0) and (CbEstacao.Items.Count = 2) then
    Escolher := 1;   { uma so' livre: ja' sugere }
  CbEstacao.ItemIndex := Escolher;
  AtualizarDetalhe;
end;

procedure PreencherLinhas;
var
  J: Integer;
begin
  CbLinha.Items.Clear;
  for J := 0 to GetArrayLength(Cat) - 1 do
    if (Cat[J].Planta = CodDe(CbPlanta)) and (Cat[J].Secao = CodDe(CbSecao)) then
      AddUnico(CbLinha, Rotulo(Cat[J].Linha, Cat[J].LinhaNome));
  if CbLinha.Items.Count > 0 then
    CbLinha.ItemIndex := 0;
  PreencherEstacoes;
end;

procedure PreencherSecoes;
var
  J: Integer;
begin
  CbSecao.Items.Clear;
  for J := 0 to GetArrayLength(Cat) - 1 do
    if Cat[J].Planta = CodDe(CbPlanta) then
      AddUnico(CbSecao, Rotulo(Cat[J].Secao, Cat[J].SecaoNome));
  if CbSecao.Items.Count > 0 then
    CbSecao.ItemIndex := 0;
  PreencherLinhas;
end;

{ Posiciona as listas na estacao deste PC (ou na do /STATION=), se houver }
procedure PosicionarEm(Estacao: String);
var
  J: Integer;
begin
  for J := 0 to GetArrayLength(Cat) - 1 do
    if (Cat[J].Estacao = Estacao) and (Cat[J].Status <> 'OCUPADA') then begin
      CbPlanta.ItemIndex := CbPlanta.Items.IndexOf(Rotulo(Cat[J].Planta, Cat[J].PlantaNome));
      PreencherSecoes;
      CbSecao.ItemIndex := CbSecao.Items.IndexOf(Rotulo(Cat[J].Secao, Cat[J].SecaoNome));
      PreencherLinhas;
      CbLinha.ItemIndex := CbLinha.Items.IndexOf(Rotulo(Cat[J].Linha, Cat[J].LinhaNome));
      PreencherEstacoes;
      Exit;
    end;
end;

procedure PreencherPlantas;
var
  J: Integer;
  Alvo: String;
begin
  CbPlanta.Items.Clear;
  for J := 0 to GetArrayLength(Cat) - 1 do
    AddUnico(CbPlanta, Rotulo(Cat[J].Planta, Cat[J].PlantaNome));
  if CbPlanta.Items.Count > 0 then
    CbPlanta.ItemIndex := 0;
  PreencherSecoes;

  Alvo := UpperCase(Trim(Param('STATION', '')));
  for J := 0 to GetArrayLength(Cat) - 1 do
    if Cat[J].Status = 'ESTE_PC' then
      Alvo := Cat[J].Estacao;
  if Alvo <> '' then
    PosicionarEm(Alvo);
end;

procedure CbPlantaChange(Sender: TObject);
begin
  PreencherSecoes;
end;

procedure CbSecaoChange(Sender: TObject);
begin
  PreencherLinhas;
end;

procedure CbLinhaChange(Sender: TObject);
begin
  PreencherEstacoes;
end;

procedure CbEstacaoChange(Sender: TObject);
begin
  AtualizarDetalhe;
end;


{ --------------------------------------------------------- pagina e fluxo }

function NovoRotulo(Texto: String; Top, Left, Width: Integer): TNewStaticText;
begin
  Result := TNewStaticText.Create(PageEstacao);
  Result.Parent := PageEstacao.Surface;
  Result.Caption := Texto;
  Result.Top := Top;
  Result.Left := Left;
  Result.Width := Width;
end;

function NovaLista(Top, Left, Width: Integer; Evento: TNotifyEvent): TNewComboBox;
begin
  Result := TNewComboBox.Create(PageEstacao);
  Result.Parent := PageEstacao.Surface;
  Result.Style := csDropDownList;
  Result.Top := Top;
  Result.Left := Left;
  Result.Width := Width;
  Result.OnChange := Evento;
end;

procedure CriarPaginaEstacao(Depois: Integer);
var
  W, Meia, Y: Integer;
begin
  PageEstacao := CreateCustomPage(Depois,
    'Estação deste PC',
    'Escolha no cadastro do servidor Proteus qual estação este PC vai ser');
  W := PageEstacao.SurfaceWidth;
  Meia := (W - ScaleX(12)) div 2;
  Y := 0;
  NovoRotulo('Planta:', Y, 0, Meia);
  NovoRotulo('Seção:', Y, Meia + ScaleX(12), Meia);
  CbPlanta := NovaLista(Y + ScaleY(16), 0, Meia, @CbPlantaChange);
  CbSecao  := NovaLista(Y + ScaleY(16), Meia + ScaleX(12), Meia, @CbSecaoChange);
  Y := Y + ScaleY(46);
  NovoRotulo('Linha:', Y, 0, W);
  CbLinha := NovaLista(Y + ScaleY(16), 0, W, @CbLinhaChange);
  Y := Y + ScaleY(46);
  NovoRotulo('Estação / fonte de log (só as livres):', Y, 0, W);
  CbEstacao := NovaLista(Y + ScaleY(16), 0, W, @CbEstacaoChange);
  Y := Y + ScaleY(48);
  LblDetalhe := NovoRotulo('', Y, 0, W);
  LblDetalhe.AutoSize := False;
  LblDetalhe.WordWrap := True;
  LblDetalhe.Height := ScaleY(56);
  Y := Y + ScaleY(60);
  LblPC := NovoRotulo('', Y, 0, W);
  LblPC.AutoSize := False;
  LblPC.WordWrap := True;
  LblPC.Height := ScaleY(44);

  PageEspera := CreateOutputProgressPage('Proteus Client', 'Consultando o servidor');
end;

{ Estacao e fonte vem da lista: na pagina seguinte ficam so' para leitura }
procedure TravarEstacaoFonte(Travar: Boolean);
begin
  PageFonte.Edits[0].ReadOnly := Travar;
  PageFonte.Edits[1].ReadOnly := Travar;
  if Travar then begin
    PageFonte.Edits[0].Color := clBtnFace;
    PageFonte.Edits[1].Color := clBtnFace;
  end else begin
    PageFonte.Edits[0].Color := clWindow;
    PageFonte.Edits[1].Color := clWindow;
  end;
end;

{ Clique em Avancar na pagina da senha: le o catalogo e testa a conexao.
  Devolve False para ficar na pagina (o tecnico quer corrigir). }
function DepoisDaSenha: Boolean;
begin
  Result := True;
  CarregarCatalogo;
  if CatOK then begin
    if not AtualizacaoCfg20 then begin
      PreencherPlantas;
      TravarEstacaoFonte(True);
    end;
    Exit;
  end;
  TravarEstacaoFonte(False);
  if not PodeRodarAjudante then begin
    MsgBox(CatErro + #13#10#13#10 +
           'Digite a estação na próxima página ou vincule depois, na tela FONTES DESTE PC.',
           mbInformation, MB_OK);
    Exit;
  end;
  Result := MsgBox('Não foi possível consultar o servidor Proteus:' + #13#10#13#10 + CatErro + #13#10#13#10 +
                   'Sim = voltar e corrigir banco, usuário ou senha.' + #13#10 +
                   'Não = continuar assim mesmo (estação digitada à mão ou vinculada depois).',
                   mbError, MB_YESNO) = IDNO;
end;

{ Clique em Avancar na pagina da estacao: reserva o slot no servidor }
function ReservarSlot: Boolean;
var
  I: Integer;
  L: TArrayOfString;
  Est, Res, Msg: String;
  Ok: Boolean;
begin
  Result := True;
  I := -1;
  if (CbEstacao.ItemIndex >= 0) and (CbEstacao.ItemIndex < GetArrayLength(IdxEstacao)) then
    I := IdxEstacao[CbEstacao.ItemIndex];
  if I < 0 then begin
    PageFonte.Values[0] := '';
    PageFonte.Values[1] := '';
    Exit;     { vincular depois: a pagina da fonte e' pulada }
  end;
  Est := Cat[I].Estacao;

  if (SlotReservado <> '') and (SlotReservado <> Est) then
    MsgBox('A estação ' + SlotReservado + ' já foi reservada para este PC nesta instalação.' + #13#10 +
           'Se ela não for usada aqui, peça a liberação do vínculo no painel Proteus.',
           mbInformation, MB_OK);

  if SlotReservado <> Est then begin
    PageEspera.SetText('Reservando a estação ' + Est + '...', 'O servidor confere se ela continua livre.');
    PageEspera.Show;
    try
      Ok := RodarAjudante('vincular', Est, L);
    finally
      PageEspera.Hide;
    end;
    if Ok then Res := CampoN(L[0], 0) else Res := '';
    if Res = 'OK' then begin
      SlotReservado := Est;
      Log('wizard: estacao ' + Est + ' reservada para o PC ' + CampoN(L[0], 1));
    end else if Res = 'RECUSADO' then begin
      MsgBox('O servidor recusou a estação ' + Est + ':' + #13#10#13#10 + CampoN(L[0], 1) + #13#10#13#10 +
             'A lista foi atualizada. Escolha outra estação ou peça a liberação no painel Proteus.',
             mbError, MB_OK);
      CarregarCatalogo;
      if CatOK then
        PreencherPlantas;
      Result := False;
      Exit;
    end else begin
      if Ok then Msg := CampoN(L[0], 1) else Msg := 'o Proteus Client não rodou.';
      if MsgBox('Não foi possível reservar a estação ' + Est + ' agora: ' + Msg + #13#10#13#10 +
                'Continuar assim mesmo? O cliente tenta vincular quando abrir.',
                mbConfirmation, MB_YESNO) = IDNO then begin
        Result := False;
        Exit;
      end;
    end;
  end;

  PageFonte.Values[0] := Est;
  PageFonte.Values[1] := Cat[I].Fonte;
end;

{ Paginas puladas: a da estacao sem catalogo; as duas numa atualizacao 2.0
  (o config.yaml e' preservado); a da fonte quando escolheu "vincular depois" }
function PularPaginaEstacao(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = PageEstacao.ID then
    Result := (not CatOK) or AtualizacaoCfg20
  else if PageID = PageFonte.ID then
    Result := AtualizacaoCfg20 or (CatOK and (CbEstacao.ItemIndex <= 0));
end;
