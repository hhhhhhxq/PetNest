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
Source: "..\dist\PetNest\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\PetNest"; Filename: "{app}\PetNest.exe"
Name: "{autodesktop}\PetNest"; Filename: "{app}\PetNest.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他选项："; Flags: unchecked

[Run]
Filename: "{app}\PetNest.exe"; Parameters: "--set-pets-root ""{code:GetPetsRoot}"""; Flags: runhidden waituntilterminated; Check: UseCustomPetsRoot
Filename: "{app}\PetNest.exe"; Description: "启动 PetNest"; Flags: nowait postinstall skipifsilent

[Code]
var
  PetsRootOptions: TInputOptionWizardPage;
  PetsRootDirectory: TInputDirWizardPage;

procedure InitializeWizard;
begin
  PetsRootOptions := CreateInputOptionPage(wpSelectDir,
    '高级选项', '宠物库位置',
    '默认会将可修改的宠物资源保存到当前用户的本地应用数据目录。',
    False, False);
  PetsRootOptions.Add('将宠物库保存到自定义位置');

  PetsRootDirectory := CreateInputDirPage(PetsRootOptions.ID,
    '选择宠物库位置', '选择存放可修改宠物资源的文件夹',
    '此目录将保存导入的宠物与动画时长配置。', False, '新建文件夹');
  PetsRootDirectory.Add(ExpandConstant('{localappdata}\PetNest\pets'));
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = PetsRootDirectory.ID) and (not PetsRootOptions.Values[0]);
end;

function UseCustomPetsRoot(): Boolean;
begin
  Result := PetsRootOptions.Values[0];
end;

function GetPetsRoot(Param: String): String;
begin
  Result := PetsRootDirectory.Values[0];
end;
