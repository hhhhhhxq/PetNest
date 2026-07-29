; PetNest Windows 安装包。先由根目录 build_windows.bat 生成 dist\PetNest。

[Setup]
AppId={{A6247183-E067-48E4-A2B4-19A46F8B4DD5}
AppName=PetNest
AppVersion=0.1.0
AppPublisher=PetNest
DefaultDirName={autopf}\PetNest
DefaultGroupName=PetNest
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=PetNest-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\PetNest\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: "pets\*"
Source: "..\pets\sample_pet\*"; DestDir: "{code:GetPetsRoot}\sample_pet"; Flags: recursesubdirs createallsubdirs ignoreversion; Check: ShouldInstallSamplePet

[Icons]
Name: "{autoprograms}\PetNest"; Filename: "{app}\PetNest.exe"
Name: "{autodesktop}\PetNest"; Filename: "{app}\PetNest.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他选项："; Flags: unchecked

[Run]
Filename: "{app}\PetNest.exe"; Parameters: "--set-pets-root ""{code:GetPetsRoot}"""; Flags: runhidden waituntilterminated
Filename: "{app}\PetNest.exe"; Description: "启动 PetNest"; Flags: nowait postinstall skipifsilent

[Code]
var
  PetsRootDirectory: TInputDirWizardPage;
  PetsRootIsAutomatic: Boolean;
  UpdatingPetsRoot: Boolean;

procedure PetsRootChanged(Sender: TObject);
begin
  if not UpdatingPetsRoot then
    PetsRootIsAutomatic := False;
end;

procedure InitializeWizard;
begin
  PetsRootDirectory := CreateInputDirPage(wpSelectDir,
    '宠物库位置（可选）', '确认可修改宠物资源的保存位置',
    '默认位置会根据程序安装位置自动选择。点击“浏览…”选择基础文件夹后，会自动创建 PetNest\pets；也可直接编辑最终宠物库路径。',
    False, '新建文件夹');
  PetsRootDirectory.Add('');
  PetsRootDirectory.Edits[0].OnChange := @PetsRootChanged;
  PetsRootIsAutomatic := True;
end;

function PathIsInside(const Candidate, Parent: String): Boolean;
var
  NormalizedCandidate, NormalizedParent: String;
begin
  NormalizedCandidate := AddBackslash(RemoveBackslashUnlessRoot(Candidate));
  NormalizedParent := AddBackslash(RemoveBackslashUnlessRoot(Parent));
  Result := CompareText(Copy(NormalizedCandidate, 1, Length(NormalizedParent)), NormalizedParent) = 0;
end;

function DefaultPetsRoot: String;
begin
  if PathIsInside(WizardDirValue, ExpandConstant('{autopf}')) then
    Result := ExpandConstant('{localappdata}\PetNest\pets')
  else
    Result := AddBackslash(WizardDirValue) + 'pets';
end;

function HasPetsSuffix(const Value: String): Boolean;
var
  NormalizedValue, PetsSuffix: String;
begin
  PetsSuffix := '\PetNest\pets';
  NormalizedValue := RemoveBackslashUnlessRoot(Trim(Value));
  Result := (Length(NormalizedValue) >= Length(PetsSuffix)) and
    (CompareText(Copy(NormalizedValue, Length(NormalizedValue) - Length(PetsSuffix) + 1, Length(PetsSuffix)), PetsSuffix) = 0);
end;

function FinalizePetsRoot(const Value: String): String;
var
  NormalizedValue: String;
begin
  NormalizedValue := RemoveBackslashUnlessRoot(Trim(Value));
  if NormalizedValue = '' then
    Result := DefaultPetsRoot
  else if HasPetsSuffix(NormalizedValue) then
    Result := NormalizedValue
  else
    Result := AddBackslash(NormalizedValue) + 'PetNest\pets';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = PetsRootDirectory.ID) and PetsRootIsAutomatic then begin
    UpdatingPetsRoot := True;
    try
      PetsRootDirectory.Values[0] := DefaultPetsRoot;
    finally
      UpdatingPetsRoot := False;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  if (CurPageID = PetsRootDirectory.ID) and not PetsRootIsAutomatic then
    PetsRootDirectory.Values[0] := FinalizePetsRoot(PetsRootDirectory.Values[0]);
  Result := True;
end;

function GetPetsRoot(Param: String): String;
begin
  Result := PetsRootDirectory.Values[0];
end;

function ShouldInstallSamplePet: Boolean;
begin
  Result := not DirExists(AddBackslash(GetPetsRoot('')) + 'sample_pet');
end;
