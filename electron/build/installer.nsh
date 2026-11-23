; 前端控制台 NSIS 定制（2026-11-23 用户令：安装包升级/卸载必须保住用户数据；
; 安装器要有过程显示。经三轮对抗审计修订）
;
; 过程显示：官方模板 ShowInstDetails nevershow（common.nsh）且其解析在
; 自定义 include 之后——属性后写覆盖先写（makensis 双 OutFile 实验实证）。
; 改用运行时指令 SetDetailsView show（NSIS 文档 4.8.1.39 背书）：
;   ① 本文件在生成脚本里位于模板之前 → 这里的隐藏 section 是第 0 个
;      section，在 InstFiles 页一打开就执行、抢在解包之前展开详情窗口
;   ② 卸载侧在 customRemoveFiles 开头同款强开
;
; 数据保障（Setup 形态真实数据目录 = $INSTDIR\resources\backend\data——
; 后端 frozen 的 _app_dir()=exe 旁=resources\backend，对抗审计实锤）：
;   customRemoveFiles 接管内置「删光 $INSTDIR」：顶层全清但跳过 resources；
;   resources\backend 下除 data\ 外全清——升级链路与卸载一律幸存用户数据。
;   customUnInstall   交互卸载弹「是否保留用户数据？」；静默（/S，升级/
;                      自动化）默认保留（/SD IDYES）。选「否」=彻底清除：
;                      data\ 与两处 userData（锚点 frontend-console-shell +
;                      壳 userData 前端控制台）一并删除。
; 配套：package.json nsis.deleteAppDataOnUninstall=false（默认不动 APPDATA——
; 只在用户明确选「不保留」时由本文件清除）。
; 本文件必须保持 UTF-8 带 BOM（手工 makensis 对无 BOM 的中文 .nsh 报
; Bad text encoding，实测；electron-builder 流程两者皆可，BOM 防手工踩坑）。

!ifdef BUILD_UNINSTALLER
; Var 只在卸载器趟被引用——安装器趟不展开本文件的宏，无条件声明会触发
; warning 6001（未引用变量），-WX 下直接构建失败（对抗审计实证）
Var fcKeepUserData     ; ""=未问（静默/升级，视为保留） "1"=保留 "0"=彻底清除
!endif

; ---- LogicLib 必须在此显式引入（第五轮 K1 阻断，实测）----
; 本文件在模板的 common.nsh **之前**解析，而 LogicLib 是 common.nsh 经
; x64.nsh / WinVer.nsh 间接带进来的。以前的 ${If} 都在 !macro 体内，展开时
; LogicLib 早已就绪；现在下面的 un.fcRmTree 是**立即解析**的 Function，
; 用到 ${If} 时 LogicLib 还没定义 → `Invalid command: "${If}"`，两趟编译
; 全挂。LogicLib.nsh 自带 include guard，与模板重复包含无害。
!include LogicLib.nsh

; ---- 过程显示：隐藏 section（"-"前缀不进组件页），section 按定义顺序执行，
; 本文件先于模板解析 → 此处第一个跑，InstFiles 页一开即展开详情 ----
Section "-fcShowDetails"
  SetDetailsView show
  DetailPrint "［前端控制台］安装过程详情已开启"
SectionEnd

; ---- junction 守卫（第四轮 J1 高危，makensis 实跑实证）----
; NSIS 的 RMDir /r 会**穿透**目录联接/符号链接，把链接指向的安装目录外的
; 真实数据整棵删掉——用户把 data\ 或日志目录迁到别的盘后留个链接是常见
; 做法，于是「保留用户数据」分支照样删光外部数据。
;
; 实测量到的事实（每次都是独立受害目录，报告与磁盘现场交叉验证）：
;   GetFileAttributesW：联接=1040、普通目录=16、悬空联接=1040、不存在=-1
;   RMDir /r 作用于联接本身        ：穿透，受害文件 DELETED
;   非递归 RMDir 作用于联接        ：只摘链接，受害文件 ALIVE
;   RMDir /r 作用于**普通目录**    ：其中任意深度套着的联接照样被穿透
; 最后一行是关键：只判断「被删路径自己是不是链接」是不够的——普通目录
; 里面的链接防不住。所以不能用 RMDir /r，必须自己逐层枚举、遇到链接只
; 摘链接。下面的 fcRmTree 就是这个递归。
;
; 另外两个实测得到的坑，改这里之前务必知道：
;   ① -1（0xFFFFFFFF）与 0x400 按位与为真——路径不存在必须显式排除。
;   ② 宏里不能用相对跳转（+2 / Goto 标签）做条件分支：展开后的层数无法
;      靠推演保证，首版宏因此把普通目录/文件/不存在全判成了链接。
;      条件一律走 LogicLib。
;
; fcRmTree 终验 13/13 PASS（嵌套/深层/顶层/带空格括号的联接目标全部幸存；
; 含链接目录、纯目录树、悬空联接、自指环目录、普通文件全部删净；栈平衡；
; 不存在的路径不崩）。改这个函数后必须重跑同款实跑验证——只看编译通过
; 不算数，本会话里「编译通过但行为全错」的版本出现过不止一次。

!macro _FC_ISLINK PATH OUTVAR
  System::Call 'kernel32::GetFileAttributesW(w "${PATH}") i .r0'
  StrCpy ${OUTVAR} 0
  ${If} $0 != -1
    IntOp $R9 $0 & 0x400
    ${If} $R9 != 0
      StrCpy ${OUTVAR} 1
    ${EndIf}
  ${EndIf}
!macroend

; ---- 卸载专用的递归删除函数 ----
; 【必须包在 !ifdef BUILD_UNINSTALLER 里】（第五轮 K3 阻断，实测）
;   函数名带 un. 前缀 → 属于「卸载器代码」。安装器趟不定义 BUILD_UNINSTALLER，
;   若照样解析到它，makensis 报 warning 6020（Uninstaller script code found
;   but WriteUninstaller never used），-WX 下直接失败。
; 【函数名必须带 un. 前缀】（第五轮 K2 阻断，实测）
;   它在卸载段被 Call——NSIS 规定卸载段只能调用 un. 开头的函数，否则
;   `Call must be used with function names starting with "un."`。
; un.fcRmTree：自实现递归删除，全程不出现 RMDir /r。
; 协议：调用方 Push 路径 / Call un.fcRmTree / Pop 一次，栈净效果为零。
;   Exch $R7 取参（$R7 旧值落到栈顶）……结尾 Pop $R7 取回旧值，此时栈顶
;   正是调用方 Push 的那个槽，再 Push "" 放返回值，调用方 Pop 一次即平。
; 占用 $R7 $R8 $R9 $0-$3，进出全部恢复，可重入；调用方需自行保存这几个。
!ifdef BUILD_UNINSTALLER
Function un.fcRmTree
  Exch $R7
  Push $R8
  Push $R9
  Push $0
  Push $1
  Push $2
  Push $3
  !insertmacro _FC_ISLINK "$R7" $R8
  ${If} $R8 == 1
    RMDir "$R7"                 ; 链接（含悬空）：非递归，只摘链接本身
  ${ElseIf} ${FileExists} "$R7\*.*"
    FindFirst $1 $2 "$R7\*.*"
    fcTreeLoop:
      StrCmp $2 "" fcTreeDone
      StrCmp $2 "." fcTreeNext
      StrCmp $2 ".." fcTreeNext
      Push "$R7\$2"
      Call un.fcRmTree           ; 下钻：目录则递归，链接则只摘链接
      Pop $3
    fcTreeNext:
      FindNext $1 $2
      Goto fcTreeLoop
    fcTreeDone:
      FindClose $1
      RMDir "$R7"                ; 此时已空，非递归
  ${Else}
    Delete "$R7"                 ; 文件，或不存在（空操作）
  ${EndIf}
  Pop $3
  Pop $2
  Pop $1
  Pop $0
  Pop $R9
  Pop $R8
  Pop $R7
  Push ""
FunctionEnd
!endif

; _FC_RMTREE <路径>：对外统一入口（链接/目录/文件/不存在 四种都处理）
; 自己保存/恢复 $3（第五轮 K4）：返回值用 Pop $3 接，而清除分支里的调用
; 发生在 customRemoveFiles 的寄存器恢复**之后**，不自带保存就会把调用方的
; $3 冲成空串。
!macro _FC_RMTREE PATH
  Push $3
  Push "${PATH}"
  Call un.fcRmTree
  Pop $3
  Pop $3
!macroend

!macro customUnInstall
  ; 升级链路（--updated）与静默卸载绝不询问、默认保留；仅交互卸载才问
  ${ifNot} ${isUpdated}
  ${andIfNot} ${Silent}
    ; 复审 N6:YESNOCANCEL——X/取消绝不能落入最破坏性的「清除」分支
    MessageBox MB_YESNOCANCEL|MB_ICONQUESTION "是否保留用户数据？$\n$\n\
      保留：工具目录里的数据与配置、本工具在 %APPDATA% 下的设置（含已存$\n\
      密码、网页登录态）留在原处；重装到同一目录即可继续使用。$\n\
      不保留：以上内容将被清除。若你把数据目录迁到了别处（如 D 盘），$\n\
      那里的数据不会被删除，但「数据在哪」的记录会一起清掉，$\n\
      重装后需在设置里重新指定该目录。$\n$\n\
      （无论选哪个，程序文件都会被正常卸载；「取消」= 放弃本次卸载）" \
      /SD IDYES IDYES fcKeep IDNO fcWipe
    ; NSIS MessageBox 至多两对分支跳转（usage 实证）——取消/X 不占名额：
    ; YES/NO 都跳走，落到下一行即取消路径 → 终止卸载（复审 N6）
    Goto fcCancel
    fcCancel:
      Abort                            ; 复审 N6:用户点 X/取消=反悔,终止卸载
    fcKeep:
      StrCpy $fcKeepUserData "1"
      Goto fcAsked
    fcWipe:
      StrCpy $fcKeepUserData "0"
    fcAsked:
  ${endif}
!macroend

!macro customRemoveFiles
  ; ---- 卸载过程显示 ----
  SetDetailsView show
  DetailPrint "［前端控制台］正在移除程序文件（保留用户数据目录 resources\backend\data）"

  ; ---- 替换内置 RMDir /r $INSTDIR：顶层除 resources 外全清 ----
  ; 寄存器约定：$R1/$R2 = resources 层的 FindFirst 句柄与枚举变量；
  ; $R3/$R4 = backend 子循环的句柄与枚举变量（独立于外层，子循环内不必
  ; 再 Push/Pop 外层的值）。
  ; fcRmTree 占用 $R7 $R8 $R9 $0 $1 $2 $3，且 _FC_RMTREE 用 Pop $3 接返回值
  ; ——这八个全部在此保存/恢复：官方模板在本宏之后还要继续用寄存器。
  ; 循环变量刻意选在 $R1-$R4，与 fcRmTree 的占用集不相交。
  ; 宏已自带「链接/目录/文件/不存在」四分流，调用点不再写 IfFileExists 分支。
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  Push $R7
  Push $R8
  Push $R9
  Push $0
  Push $1
  Push $2
  Push $3
  FindFirst $R1 $R2 "$INSTDIR\*.*"
  fcRmLoop:
    StrCmp $R2 "" fcRmDone
    StrCmp $R2 "." fcRmNext
    StrCmp $R2 ".." fcRmNext
    StrCmp $R2 "data" fcRmNext        ; 复审 N5:旧 zip 布局的顶层 data\ 也保
    StrCmp $R2 "resources" fcRmNext   ; ↓ 下一循环单独处理（内含用户数据目录）
    !insertmacro _FC_RMTREE "$INSTDIR\$R2"
    fcRmNext:
      FindNext $R1 $R2
      Goto fcRmLoop
  fcRmDone:
    FindClose $R1

  ; ---- resources\：backend\（后端 extraResources）下除 data\ 外全清，
  ;      其余（app.asar / 前端控制台.exe 等）照删 ----
  FindFirst $R1 $R2 "$INSTDIR\resources\*.*"
  fcResLoop:
    StrCmp $R2 "" fcResDone
    StrCmp $R2 "." fcResNext
    StrCmp $R2 ".." fcResNext
    StrCmp $R2 "backend" 0 fcResRm
      ; backend\ 下仅保 data\（Setup 形态默认数据目录）
      FindFirst $R3 $R4 "$INSTDIR\resources\backend\*.*"
      fcBeLoop:
        StrCmp $R4 "" fcBeDone
        StrCmp $R4 "." fcBeNext
        StrCmp $R4 ".." fcBeNext
        StrCmp $R4 "data" fcBeNext      ; 用户数据目录：无条件保留
        !insertmacro _FC_RMTREE "$INSTDIR\resources\backend\$R4"
        fcBeNext:
          FindNext $R3 $R4
          Goto fcBeLoop
      fcBeDone:
        FindClose $R3
      Goto fcResNext
    fcResRm:
      !insertmacro _FC_RMTREE "$INSTDIR\resources\$R2"
    fcResNext:
      FindNext $R1 $R2
      Goto fcResLoop
  fcResDone:
    FindClose $R1
  Pop $3
  Pop $2
  Pop $1
  Pop $0
  Pop $R9
  Pop $R8
  Pop $R7
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1

  ; 用户明确选了「不保留」→ 彻底清除：数据目录 + 两处 userData。
  ; per-machine 安装时卸载段运行在 all 语境——$APPDATA 会指向公共目录，
  ; 切到 current 删完再切回（对齐官方模板 uninstaller.nsh:232-248）
  ; 这几处同样走 _FC_RMTREE：data\ 若是指向外部的链接，只摘链接，
  ; 不去删链接指向的真实数据（范围不超出用户明确同意的"本工具数据"）
  ${if} $fcKeepUserData == "0"
    DetailPrint "［前端控制台］按用户选择彻底清除用户数据与配置……"
    ${if} $installMode == "all"
      SetShellVarContext current
    ${endif}
    !insertmacro _FC_RMTREE "$INSTDIR\resources\backend\data"
    !insertmacro _FC_RMTREE "$APPDATA\frontend-console-shell"
    !insertmacro _FC_RMTREE "$APPDATA\前端控制台"
    ; 文件关联解压的图标缓存（后端 file_assoc.py 建的，属于本工具）
    !insertmacro _FC_RMTREE "$LOCALAPPDATA\SerialConsolePro"
    ${if} $installMode == "all"
      SetShellVarContext all
    ${endif}
    ; 复审②:用户明确选了「不保留」→ 顶层 legacy data\(旧 zip 布局)也清,
    ; 文案承诺才成立(保留分支仍无条件保它——升级/保留场景的安全侧)
    !insertmacro _FC_RMTREE "$INSTDIR\data"
    ; 复审 N7+①:回收空目录壳(非递归 RMDir 仅空目录生效)。SetOutPath
    ; 先移出 $INSTDIR——un.onInit 把进程 CWD 设在了那里,不挪走 RMDir
    ; $INSTDIR 会被自己锁死(官方模板同款处理)
    SetOutPath $TEMP
    RMDir "$INSTDIR\resources\backend"
    RMDir "$INSTDIR\resources"
    RMDir "$INSTDIR"
  ${else}
    DetailPrint "［前端控制台］用户数据目录已保留：$INSTDIR\resources\backend\data"
  ${endif}
!macroend
