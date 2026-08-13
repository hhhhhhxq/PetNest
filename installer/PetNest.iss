; PetNest Windows 安装包。先由根目录 build_windows.bat 生成 dist\PetNest。

#ifndef AppVersion
#define AppVersion "0.1.4"
#endif

[Setup]
AppId={{A6247183-E067-48E4-A2B4-19A46F8B4DD5}
AppName=PetNest
AppVersion={#AppVersion}
AppPublisher=PetNest
SetupIconFile=..\assets\icons\petnest-app.ico
DefaultDirName={autopf}\PetNest
DefaultGroupName=PetNest
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename=PetNest-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\PetNest\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: "pets\*"
Source: "..\dist\PetNestUpdater.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pets\sample_pet\*"; DestDir: "{code:GetPetsRoot}\sample_pet"; Flags: recursesubdirs createallsubdirs ignoreversion; Check: SamplePetNeedsRepair

[Icons]
Name: "{autoprograms}\PetNest"; Filename: "{app}\PetNest.exe"
Name: "{autodesktop}\PetNest"; Filename: "{app}\PetNest.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他选项："; Flags: unchecked

[Run]
Filename: "{app}\PetNest.exe"; Parameters: "--set-pets-root ""{code:GetPetsRoot}"""; Flags: runhidden waituntilterminated skipifsilent
Filename: "{app}\PetNest.exe"; Description: "启动 PetNest"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""PetNest LAN UDP 18487"""; Flags: runhidden waituntilterminated; RunOnceId: "RemovePetNestLanFirewall"

[Code]
const
  FirewallRuleName = 'PetNest LAN UDP 18487';

var
  PetsRootDirectory: TInputDirWizardPage;
  FirewallPage: TInputOptionWizardPage;
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

  FirewallPage := CreateInputOptionPage(PetsRootDirectory.ID,
    '局域网互动防火墙', '允许附近设备发现 PetNest',
    '安装器会创建一条仅允许 PetNest 使用 UDP 18487 的入站规则。默认只允许专用网络；公用网络通常包括咖啡店、机场等不可信网络，请谨慎开启。',
    False, False);
  FirewallPage.Add('允许在公用网络中使用局域网互动（可选）');
  FirewallPage.Values[0] := False;
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

function GetFirewallProfiles(Param: String): String;
begin
  if FirewallPage.Values[0] then
    Result := 'private,public'
  else
    Result := 'private';
end;

function ExecNetsh(const Parameters: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\netsh.exe'), Parameters, '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure ConfigureFirewallRule;
var
  Profiles: String;
  Parameters: String;
begin
  Profiles := GetFirewallProfiles('');
  ExecNetsh('advfirewall firewall delete rule name="' + FirewallRuleName + '"');
  Parameters :=
    'advfirewall firewall add rule name="' + FirewallRuleName +
    '" dir=in action=allow protocol=UDP localport=18487 program="' +
    ExpandConstant('{app}\PetNest.exe') + '" profile=' + Profiles + ' enable=yes';
  if not ExecNetsh(Parameters) then
    MsgBox('防火墙规则创建失败。PetNest 仍可启动，但局域网设备可能无法发现它。' + #13#10 +
      '你可以将当前网络改为“专用网络”，或在 Windows 防火墙中允许 UDP 18487。',
      mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ConfigureFirewallRule;
end;

function SamplePetNeedsRepair: Boolean;
begin
  Result :=
    not FileExists(AddBackslash(GetPetsRoot('')) + 'sample_pet\pet.json') or
    not FileExists(AddBackslash(GetPetsRoot('')) + 'sample_pet\animations\idle\001.png');
end;
