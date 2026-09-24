#!/usr/bin/env python3
# yuMAArin — 轻量 GTK4 前端驱动 maa-cli。任务与参数按 MAA 官方集成文档（任务类型一览）定义。
import gi, json, os, re, subprocess, datetime, shlex
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, GLib, Gdk, Gio, GObject

MAA = os.path.expanduser("~/.local/bin/maa")
ADB = os.path.expanduser("~/.local/bin/adb")
TASKS_FILE = os.path.expanduser("~/.config/maa/tasks/ui.json")
PROFILE = os.path.expanduser("~/.config/maa/profiles/default.json")
STATE_FILE = os.path.expanduser("~/.config/yumaarin/state.json")
QUEUE_FILE = os.path.expanduser("~/.config/yumaarin/queue.json")   # 任务队列（模块/参数/勾选）持久化
DEFAULT_ADDR = "192.168.240.112:5555"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
CLIENTS = [("Official","官服"),("Bilibili","Bilibili服"),("YoStarEN","国际服 (YostarEN)"),
           ("YoStarJP","日服 (YostarJP)"),("YoStarKR","韩服 (YostarKR)"),("Txwy","繁中服 (txwy)")]
SERVERS = [("CN","国服"),("US","美服"),("JP","日服"),("KR","韩服")]
# 服务器由客户端类型推导（官方不单独给服务器设置）
SERVER_OF_CLIENT = {"Official":"CN","Bilibili":"CN","Txwy":"CN",
                    "YoStarEN":"US","YoStarJP":"JP","YoStarKR":"KR"}

def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except Exception: return {}

def save_state(d):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f: json.dump(d, f)
    except Exception: pass

def load_stages():
    try:
        d = json.load(open(os.path.expanduser("~/.local/share/maa/resource/stages.json"), encoding="utf-8"))
        return sorted({x.get("code") for x in d if x.get("code")})
    except Exception:
        return ["1-7", "CE-6"]
STAGES = load_stages()
# 剿灭的特殊取值（来自官方文档）
ANNIHILATION = ["Annihilation", "Chernobog@Annihilation", "LongMen@Annihilation",
                "Yan@Annihilation", "Siesta@Annihilation", "FONV@Annihilation"]

# ---- 任务目录 ----
# 可加任务 = 官方长草 TaskTypeList（去掉用户明确不做的 干员养成/更新数据/库存保持）；
# 官方把 抄作业 放在「自动战斗」页，故长草不放 Copilot/SSS/悖论。
# param: (key, 标签, kind, 默认, choices[, extra])；("group", 标题) 为分组表头
#   kind: group/bool/int/float/str/ints/strs/enum/file/json/kv/rows/text
TASKS = [
 dict(type="StartUp", label="开始唤醒", custom="startup", params=[
    ("group","唤醒"),
    ("start_game_enabled","自动启动客户端","bool",True,None),
    ("group","账号切换"),
    ("account_name","账号(已登录名，可空)","str","",None)]),
 # 关闭游戏无可调参数（客户端为全局设置，下发时注入）
 dict(type="CloseDown", label="关闭游戏", params=[]),
 dict(type="Fight", label="理智作战", custom="fight", params=[
    ("group","关卡与次数"),
    ("stage","关卡","enum","",[("","当前/上次"),("Annihilation","当期剿灭"),("Chernobog@Annihilation","切尔诺伯格"),("LungmenOutskirts@Annihilation","龙门外环"),("LungmenDowntown@Annihilation","龙门市区")] + [(x, x) for x in STAGES]),
    ("times","作战次数","int","0",None),
    ("series","代理倍率","enum","0",[("0","自动"),("10","10"),("9","9"),("8","8"),("7","7"),("6","6"),("5","5"),("4","4"),("3","3"),("2","2"),("1","1"),("-1","不切换")]),
    ("group","理智与源石"),
    ("medicine","使用药剂(数量)","int","0",None),
    ("medicine_expire_days","使用临期药(天数)","int","0",None),
    ("stone","使用源石(数量)","int","0",None),
    ("DrGrandet","博朗台(碎石省理智)","bool",False,None),
    ("group","指定材料"),
    ("drops","指定掉落","kv",{},None,{"key_label":"物品ID(如 30011)","val_label":"目标数量","val_type":"int"})]),
 # 数据上报（企鹅/一图流）、服务器、客户端均为全局（设置→三方服务 / 游戏），下发时注入
 dict(type="Infrast", label="基建换班", custom="infrast", params=[
    ("group","换班模式"),
    ("mode","基建模式","enum","0",[("0","常规模式"),("20000","队列轮换"),("10000","自定义基建配置")]),
    ("facility","换班设施","strs","Mfg,Trade,Power,Control,Reception,Office,Dorm",None),
    ("drones","无人机用途","enum","Money",[("_NotUse","不使用无人机"),("Money","贸易站-龙门币"),("SyntheticJade","贸易站-合成玉"),("CombatRecord","制造站-经验书"),("PureGold","制造站-赤金"),("OriginStone","制造站-源石碎片"),("Chip","制造站-芯片组")]),
    ("group","自定义排班(仅自定义模式)"),
    ("filename","自定义基建文件","str","",None),
    ("plan_index","方案序号","int","0",None),
    ("group","宿舍"),
    ("threshold","宿舍心情阈值(0-100)","int","30",None),
    ("dorm_notstationed_enabled","不将已进驻的干员放入宿舍","bool",True,None),
    ("dorm_trust_enabled","宿舍信赖","bool",True,None),
    ("group","制造站与会客室"),
    ("replenish","源石碎片自动补货","bool",True,None),
    ("reception_message_board","会客室留言板领取","bool",True,None),
    ("reception_clue_exchange","线索交流","bool",True,None),
    ("reception_send_clue","赠送线索","bool",True,None),
    ("continue_training","继续训练","bool",False,None),
    ("group","干员技能"),
    ("fiammetta_recovery_enabled","菲亚梅塔恢复","bool",False,None),
    ("fiammetta_targets","菲亚梅塔目标","strs","清流,可露希尔,但书",None),
    ("use_pinus_sylvestris","使用松果","bool",False,None),
    ("use_perception_information","使用感知信息","bool",False,None),
    ("use_worldly_plight","使用世事多艰","bool",False,None),
    ("use_abyssal_hunter","使用深海猎人","bool",False,None)]),
 dict(type="Recruit", label="公开招募", custom="recruit", params=[
    ("group","招募次数"),
    ("times","招募次数","int","4",None),
    ("expedite","自动使用加急许可","bool",False,None),
    ("expedite_times","加急次数(已不生效)","int","0",None),
    ("group","自动确认"),
    ("select","选择标签等级","ints","3,4,5,6",None),
    ("confirm","确认标签等级","ints","3,4",None),
    ("set_time","设置招募时限","bool",True,None),
    ("recruitment_time","招募时限(分钟)","kv",{},None,{"key_label":"等级(3/4/5/6)","val_label":"分钟","val_type":"int"}),
    ("level3_recruitment_permit_reserve","三星招募券保留(0=禁用)","int","0",None),
    ("group","标签与刷新"),
    ("refresh","刷新三星 Tag","bool",True,None),
    ("first_tags","首选 Tags","strs","",None),
    ("preserve_tags","保留并跳过的 Tags","strs","支援机械",None),
    ("extra_tags_mode","公招多选 Tag 的策略","enum","0",[("0","默认不选择额外 Tag"),("1","选择高星时总是选择三个 Tag"),("2","尽可能多地选且只选高星 Tag")]),
    ("skip_robot","跳过机器人 tag","bool",True,None)]),
 dict(type="Mall", label="信用收支", params=[
    ("group","访问与信用作战"),
    ("visit_friends","访问好友","bool",True,None),
    ("credit_fight","信用作战","bool",False,None),
    ("formation_index","信用作战编队序号","int","0",None),
    ("group","信用购物"),
    ("shopping","信用购物","bool",True,None),
    ("buy_first","优先购买","strs","招聘许可",None),
    ("blacklist","黑名单","strs","碳;家具;加急许可",None),
    ("force_shopping_if_credit_full","溢出时无视黑名单","bool",False,None),
    ("only_buy_discount","只买折扣商品","bool",False,None),
    ("reserve_max_credit","保留最大信用","bool",False,None)]),
 dict(type="Award", label="领取奖励", params=[
    ("group","领取项目"),
    ("award","每日/每周奖励","bool",True,None),
    ("mail","邮件奖励","bool",False,None),
    ("recruit","免费单抽","bool",False,None),
    ("orundum","幸运墙合成玉","bool",False,None),
    ("mining","限时开采许可","bool",False,None),
    ("specialaccess","月卡奖励","bool",False,None),
    ("signinevent","限时签到活动","bool",False,None)]),
 dict(type="Roguelike", label="自动肉鸽", custom="roguelike", params=[
    ("group","主题与策略"),
    ("theme","肉鸽主题","enum","Phantom",[("Phantom","傀影"),("Mizuki","水月"),("Sami","萨米"),("Sarkaz","萨卡兹"),("JieGarden","界园"),("BlackFlow","黑流树海")]),
    ("mode","策略","enum","0",[("0","刷等级"),("1","刷源石锭"),("4","刷开局(凹奖励)"),("6","刷月度小队"),("7","刷深入调查"),("5","刷坍缩范式(萨米)"),("20001","刷常乐节点(界园)"),("30001","刷襁褓动物(黑流)")]),
    ("difficulty","难度","int","0",None),
    ("collectible_mode_squad","烧水分队","str","",None),
    ("find_playTime_target","目标常乐节点","enum","1",[("1","令 - 掷地有声"),("2","黍 - 种因得果"),("3","年 - 三缺一")]),
    ("group","开局"),
    ("squad","开局分队","str","",None),
    ("roles","开局职业组","str","",None),
    ("core_char","核心干员","str","",None),
    ("core_char_list","开局干员顺位","rows",[],None,{"fields":[("name","干员名","str"),("use_support","借助战","bool")]}),
    ("use_support","使用助战","bool",True,None),
    ("use_nonfriend_support","使用非好友助战","bool",False,None),
    ("start_with_elite_two","精二开局","bool",False,None),
    ("only_start_with_elite_two","仅精二开局(不作战)","bool",False,None),
    ("first_floor_foldartal","第一层密文板","str","",None),
    ("start_foldartal_list","开局密文板","strs","",None),
    ("group","投资与次数"),
    ("starts_count","开始探索 999999 次后停止任务","int","999999",None),
    ("investment_enabled","投资源石锭","bool",True,None),
    ("investments_count","投资次数","int","999",None),
    ("stop_when_investment_full","存款满即停止","bool",False,None),
    ("investment_with_more_score","投资追求高分","bool",False,None),
    ("refresh_trader_with_dice","用骰子刷新商店","bool",False,None),
    ("group","停止条件"),
    ("stop_at_final_boss","到最终 Boss 停止","bool",False,None),
    ("stop_at_max_level","满级停止","bool",False,None),
    ("group","月度小队 / 深入调查 / 藏品"),
    ("monthly_squad_auto_iterate","月度小队自动切换","bool",True,None),
    ("monthly_squad_check_comms","月度小队通讯","bool",True,None),
    ("deep_exploration_auto_iterate","深入调查自动切换","bool",True,None),
    ("collectible_mode_shopping","藏品模式购物","bool",False,None),
    ("collectible_mode_start_list","刷开局期望奖励","kv",{"hot_water":True,"hope":True,"idea":True},None,{"key_label":"奖励键(hot_water/shield/ingot…)","val_label":"","val_type":"bool"}),
    ("use_foldartal","使用密文板","bool",False,None),
    ("double_check_collapsal_paradigms","二次确认坍缩范式","bool",False,None),
    ("check_collapsal_paradigms","检查坍缩范式","bool",False,None),
    ("expected_collapsal_paradigms","期望坍缩范式","strs","",None),
    ("group","黑流 / 种子"),
    ("blackflow_strategy","黑流策略","str","",None),
    ("blackflow_cultivation_target","目标襁褓动物","enum","swaddled_cat",[("swaddled_cat","襁褓中的猫"),("swaddled_feathered_serpent","襁褓羽蛇"),("swaddled_dog","襁褓中的狗"),("swaddled_cerberus","襁褓三头犬")]),
    ("start_with_seed","种子开局","str","",None)]),
 dict(type="Reclamation", label="生息演算", custom="reclamation", params=[
    ("group","主题与模式"),
    ("theme","主题","enum","Tales",[("Tales","沙洲遗闻"),("Fire","沙中之火"),("RelaunchAnchor","重启锚点")]),
    ("mode","模式","enum","1",[("0","无存档刷生息点数"),("1","有存档刷生息点数"),("16","RA-1 精耕细作循环"),("32","RA-15 60杀任务"),("48","RA-4 解锁区域")]),
    ("increment_mode","增加方式","enum","0",[("0","连点"),("1","长按")]),
    ("group","制造与商店"),
    ("tools_to_craft","制造工具","strs","",None),
    ("num_craft_batches","单次最大组装轮数","int","16",None),
    ("clear_store","任务完成后购买商店","bool",True,None)]),
 dict(type="SwitchTheme", label="更换主界面主题", params=[
    ("group","主题"),
    ("themes","候选主题","slist",[],None,{"placeholder":"游戏内主题名称，如 喜报"})]),
 dict(type="Custom", label="自定义任务", params=[
    ("group","自定义"),
    ("task_names","任务名(逗号分隔)","strs","",None),
    ("params","自定义参数(JSON)","json","",None)]),
]

# ---- 官方设置项解释（TooltipBlock，取自官方 XAML，{key=} 已解析为中文）----
TIPS = {
    'drops': '进入的关卡仍由下方 ｢关卡指定｣ / ｢候选关卡｣ 决定。\n• 刷取数量：以当前理智作战任务中该材料的掉落数量为目标，达到设定数量后停止。\n• 目标库存：会参考 ｢小工具-仓库识别｣ 中保存的库存数据，只补到设定库存为止。\n  • 库存数据是缓存值，手动刷关、合成或消耗材料后可能与实际不一致；可通过 ｢更新数据｣ 或 ｢小工具-仓库识别｣ 同步。\n  • 运行时会根据掉落实时更新库存，前序任务刷出的材料会影响后续任务的缺口计算。',
    'DrGrandet': '在恢复理智确认界面等待，直到当前的 1 点理智恢复完成再立即确认。',
    'medicine_expire_days': '只吃游戏内显示不足 N 天的理智药，显示“N 天”及以上的不吃。',
    'stage': '支持大部分主线关卡名与原列表的关卡名（如 4-10、AP-5、H10-1-Hard）\n可在关卡结尾输入 ｢Normal/Hard｣ 切换难度：10-14 章对应标准/磨难，15 章及以后对应常规/险地\n可输入 ｢SSReopen-XX｣ 一次性代理 SS 复刻的普通关',
    'expedite': '该选项仅生效一次。\n招募券获取速度低于消耗速度，正常情况下下一轮公招任务时自然已到招募时间，仅在招募券严重溢出等应急场景下使用',
    'confirm': '仅可通过修改配置文件开启此选项',
    'first_tags': '会尽可能多的选择倾向的 Tag',
    'level3_recruitment_permit_reserve': '当剩余招聘许可小于等于该值时跳过 3 星招聘',
    'preserve_tags': '识别到任一已选词条时跳过该次招募并保留该栏位；留空时不保留任何词条。',
    'threshold': '若启用自定义换班，该字段仅针对 autofill 和使用干员编组的房间有效',
    'dorm_notstationed_enabled': '勾选则不会将艾丽妮等干员从训练室移除，但也会导致加工站干员不能进入宿舍。',
    'reception_clue_exchange': '若无法开启线索交流，换班时会把线索板上的所有线索都取下来；若能开启，则会使用一键放置。\n个人线索上限为 10 张（含已放入会客室的线索），且已放入会客室的线索不计入重复判断。\n提前放入过多线索可能导致到达上限却无法一键赠送或获取新线索，只能靠好友捞起来。',
    'fiammetta_recovery_enabled': '开启后，换班开始时会将恢复目标与满心情的菲亚梅塔放入宿舍互换心情，菲亚梅塔随后留在宿舍恢复心情。',
    'use_pinus_sylvestris': '必要干员：焰尾(精二)、薇薇安娜(精二)、野鬃(精二)/灰毫(精二)/远牙(精二)至少一个\n参与计算干员：砾',
    'use_perception_information': '必要干员：絮雨(精二)、迷迭香(精二)、黑键(精二)\n参与计算干员：夕、塑心、爱丽丝、车尔尼\n优先度高于人间烟火',
    'use_worldly_plight': '必要干员：桑葚(精二)、乌有(精二)\n参与计算干员：重岳、令、夕',
    'use_abyssal_hunter': '必要干员：歌蕾蒂娅(精二)、乌尔比安、斯卡蒂、幽灵鲨、安哲拉\n因算法原因同时勾选红松骑士团时不会和红松骑士团同时参与排班',
    'credit_fight': '访问好友后借助战打一把 OF-1 赚 30 信用。\n关卡选择为 ｢当前/上次｣ 时此功能无效。\n别传 ｢火蓝之心｣ 关卡OF-1未解锁时请勿勾选。',
    'only_buy_discount': '⚠ 注意：可能会导致信用点数溢出！仍然会购买未打折的白名单物品！',
    'reserve_max_credit': '低于 300 信用点也仍然会购买白名单物品！',
    'recruit': '若不存在免费单抽，则不会抽取',
    'signinevent': '仅支持常见横向版型；其他版型不支持，可能无法正常运作',
    'difficulty': '解锁 ｢界园｣ 相关科技后，指挥分队在进行 N3 及以上难度的探索时，会额外携带一个 ｢时光之末｣，可以利用其进行 ｢一战一跳｣ 的存钱策略。\n若尚未解锁该科技，请不要选择 N3 及以上难度（包括 ｢MAX｣）进行探索；\n若希望启用此机制，请确保选择的难度为 N3 及以上（不包括 ｢不切换 (-1)｣）。',
    'first_floor_foldartal': '填写远见密文板名称，多个用英文分号 ｢;｣ 隔开',
    'start_foldartal_list': '最多写三个，并用英文分号 ｢;｣ 隔开',
    'expected_collapsal_paradigms': '用英文分号 ｢;｣ 隔开，留空将使用默认列表。',
    'monthly_squad_check_comms': '勾选后，MAA会检查是否已解锁当前小队的全部通讯，全部解锁后才会切换下一个月度小队\n若只需获取奖励，可取消勾选以减少重复探索\nMAA不会因为取消勾选此选项而提前在局内结束探索',
    'start_with_seed': '示例：2b3c4d,rogue_1,120',
    'account_name': '需要切换至的账号，留空以禁用。\n输入登录界面显示的内容，如 ｢123****4567｣，可输入 ｢123****4567｣、｢4567｣ 或 ｢23****45｣\n繁中服和韩服账号为 Email，如 ｢ab****01@gmail.com｣，建议填不含星号的明文片段，如 ｢01@gmail｣。\n仅支持官服、B服、繁中服及韩服，不支持第三方登录方式。',
    'themes': '填写游戏内主题列表中显示的主题名称。\n填写多个时每次运行随机选择一个，仅填写一个时固定切换。\n个别不常用字（如 凇、淞）识别可能出现形近偏差导致主题未找到，此时请通过 ｢问题反馈｣ 提交日志压缩包。',
}

DAILY_TYPES = {"StartUp", "Fight", "Recruit", "Infrast", "Mall", "Award"}

TOOLS = [
    ("version", "版本信息", []),
    ("activity", "活动关卡", [("CLIENT", "客户端", "Official", True, CLIENTS)]),
    ("remainder", "余数计算", [("DIVISOR", "除数", "", True, None)]),
    ("dir", "目录路径", [("DIR", "类型", "config", True, [("data","数据"),("library","库"),("config","配置"),("cache","缓存"),("resource","资源"),("hot-update","热更新"),("log","日志")])]),
    ("list", "任务列表", []),
    ("update", "更新核心/资源", [("CHANNEL", "通道", "stable", True, [("stable","稳定版"),("beta","测试版"),("alpha","内测版")])]),
    ("hot-update", "热更新资源", []),
    ("cleanup", "清理缓存", []),
]

def coerce(kind, val):
    v = val
    if kind in ("int",):
        try: return int(v)
        except Exception: return 0
    if kind == "float":
        try: return float(v)
        except Exception: return 0.0
    if kind == "ints":
        return [int(x) for x in re.split(r"[,;\s]+", str(v).strip()) if x.isdigit()]
    if kind == "strs":
        return [x for x in re.split(r"[,;\s]+", str(v).strip()) if x]
    if kind == "enum":
        try: return int(v)
        except Exception: return v
    if kind == "json":
        v = (v or "").strip()
        if not v: return None
        try: return json.loads(v)
        except Exception: return None
    if kind in ("kv", "rows", "slist"):
        return val if val not in (None, "", {}, []) else None
    if kind == "text":
        return val if (val or "").strip() else None
    return v

def widget_value(w):
    if hasattr(w, "_get"): return w._get()
    if isinstance(w, Gtk.Entry): return w.get_text().strip()
    if isinstance(w, Gtk.CheckButton): return w.get_active()
    if isinstance(w, Gtk.SpinButton): return w.get_value()
    if isinstance(w, Gtk.DropDown):
        it = w.get_selected_item(); lab = it.get_string() if it else ""
        vm = getattr(w, "_valmap", None)
        return vm.get(lab, lab) if vm else lab
    return ""

def _struct_set_row(kind, ws, init, extra):
    init = init or {}
    if kind == "kv":
        ke, vw = ws
        ke.set_text(str(init.get("_k", "")))
        vt = extra.get("val_type", "str")
        if vt == "bool": vw.set_active(bool(init.get("_v", False)))
        else: vw.set_text("" if init.get("_v", "") in (None, "") else str(init.get("_v")))
    elif kind == "slist":
        ws[0].set_text(str(init.get("_v", "")))
    else:
        for (name, label, typ), w in zip(extra.get("fields", []), ws):
            v = init.get(name)
            if typ == "bool": w.set_active(bool(v))
            elif typ == "int": w.set_text("" if v in (None, "") else str(v))
            else: w.set_text("" if v is None else str(v))

def _make_struct(kind, default, extra):
    # 复合控件：kv=键值表(对象)；rows=对象行表(对象数组)。值经 _get/_set 读写。
    extra = extra or {}
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    rows = []
    def add_row(init=None):
        init = init or {}
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        ws = []
        if kind == "kv":
            vt = extra.get("val_type", "str")
            ke = Gtk.Entry(); ke.set_placeholder_text(extra.get("key_label", "键")); ke.set_size_request(120, -1)
            vw = Gtk.CheckButton() if vt == "bool" else Gtk.Entry()
            if vt != "bool":
                vw.set_placeholder_text(extra.get("val_label", "值")); vw.set_size_request(90, -1)
            ws = [ke, vw]
        elif kind == "slist":
            e = Gtk.Entry(); e.set_placeholder_text(extra.get("placeholder", "条目")); e.set_hexpand(True)
            ws = [e]
        else:
            for (name, label, typ) in extra.get("fields", []):
                if typ == "bool":
                    w = Gtk.CheckButton(); w.set_tooltip_text(label)
                else:
                    w = Gtk.Entry(); w.set_placeholder_text(label); w.set_size_request(120, -1)
                ws.append(w)
        for w in ws: r.append(w)
        rm = Gtk.Button(label="×"); rm.set_tooltip_text("删除此行"); r.append(rm)
        rec = {"row": r, "ws": ws}
        rm.connect("clicked", lambda _b, rec=rec: (rows.remove(rec), box.remove(rec["row"])))
        rows.append(rec); box.append(r)
        _struct_set_row(kind, ws, init, extra)
        return rec
    add = Gtk.Button(label="＋ 添加"); add.set_halign(Gtk.Align.START)
    add.connect("clicked", lambda _b: add_row({}))
    box.append(add)
    def set_data(data):
        for rec in list(rows): box.remove(rec["row"])
        rows.clear()
        if kind == "kv":
            items = list((data or {}).items())
            for k, v in items: add_row({"_k": k, "_v": v})
            if not items: add_row({})
        elif kind == "slist":
            items = list(data or [])
            for it in items: add_row({"_v": it})
            if not items: add_row({})
        else:
            for item in (data or []): add_row(item)
            if not (data or []): add_row({})
    def get_data():
        if kind == "kv":
            vt = extra.get("val_type", "str"); out = {}
            for rec in rows:
                ke, vw = rec["ws"]; k = ke.get_text().strip()
                if not k: continue
                if vt == "bool": out[k] = bool(vw.get_active())
                elif vt == "int":
                    t = vw.get_text().strip()
                    if t == "": continue
                    try: out[k] = int(t)
                    except Exception: out[k] = t
                else: out[k] = vw.get_text().strip()
            return out
        if kind == "slist":
            return [r["ws"][0].get_text().strip() for r in rows if r["ws"][0].get_text().strip()]
        fields = extra.get("fields", []); out = []
        for rec in rows:
            o = {}; has = False
            for (name, label, typ), w in zip(fields, rec["ws"]):
                if typ == "bool": o[name] = bool(w.get_active())
                else:
                    t = w.get_text().strip()
                    if typ == "int":
                        if t == "": continue
                        try: o[name] = int(t)
                        except Exception: o[name] = t
                    else:
                        if t == "": continue
                        o[name] = t
                if o.get(name) not in (None, "", False): has = True
            if has: out.append(o)
        return out
    box._get = get_data; box._set = set_data; box._struct = kind
    set_data(default)
    return box

def make_widget(kind, default, choices, extra=None):
    if kind in ("kv", "rows", "slist"):
        return _make_struct(kind, default, extra)
    if kind == "bool":
        w = Gtk.CheckButton(); w.set_active(bool(default)); return w
    if kind in ("int", "float"):
        try: d = float(default) if str(default).strip() not in ("", "None") else 0.0
        except Exception: d = 0.0
        if kind == "int":
            sp = Gtk.SpinButton.new_with_range(-2147483648, 2147483647, 1); sp.set_numeric(True)
        else:
            sp = Gtk.SpinButton.new_with_range(0, 1, 0.05); sp.set_digits(2)
        sp.set_value(d); sp.set_size_request(140, -1)
        return sp
    if kind == "enum":
        vals, labs = [], []
        for c in (choices or [""]):
            if isinstance(c, (tuple, list)): vals.append(str(c[0])); labs.append(str(c[1]))
            else: vals.append(str(c)); labs.append(str(c))
        dd = Gtk.DropDown.new_from_strings(labs)
        if len(labs) > 15: dd.set_enable_search(True)
        if str(default) in vals: dd.set_selected(vals.index(str(default)))
        dd.set_size_request(150, -1); dd._valmap = dict(zip(labs, vals))
        return dd
    if kind == "text":
        tw = Gtk.TextView(); tw.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); tw.set_monospace(True)
        sw = Gtk.ScrolledWindow(); sw.set_min_content_height(54); sw.set_hexpand(True); sw.set_child(tw)
        sw._get = lambda: tw.get_buffer().get_text(
            tw.get_buffer().get_start_iter(), tw.get_buffer().get_end_iter(), False).strip()
        sw._set = lambda v: tw.get_buffer().set_text("" if v is None else str(v))
        sw._set(default)
        return sw
    if kind == "json":
        e = Gtk.Entry(); e.set_size_request(220, -1)
        e.set_placeholder_text('JSON，如 {"30011":10}')
        if default not in (None, "", []):
            try: e.set_text(json.dumps(default, ensure_ascii=False))
            except Exception: e.set_text(str(default))
        return e
    e = Gtk.Entry(); e.set_text(str(default)); e.set_size_request(150, -1)
    return e

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.yumaarin")
        self.proc = None
        self._timer_last = None
        self._mod_seq = 0

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("一键长草")
        st = load_state()
        self._install_css()
        self.apply_theme(st.get("theme", "system"))
        recall = st.get("recall_size", True)
        win.set_default_size(int(st.get("w", 820)) if recall else 820,
                             int(st.get("h", 640)) if recall else 640)
        self._build_root_view(win)
        win.connect("close-request", self.on_close)
        win.present()
        def _restore_split():
            if load_state().get("recall_size", True) and getattr(self, "log_paned", None):
                self.log_paned.set_position(int(load_state().get("split", 520)))
            return False
        GLib.idle_add(_restore_split)
        GLib.idle_add(self.auto_check_update)
        GLib.idle_add(self.refresh_version)
        GLib.timeout_add_seconds(2, self._sync_view_buttons)
        GLib.timeout_add_seconds(30, self._timer_tick)
        GLib.idle_add(self._maybe_run_daily)

    # =========================================================================
    # RootView.xaml 原样移植（对照 src/MaaWpfGui/Views/UI/RootView.xaml）
    # WPF 专有 / GTK 不支持的部件先按注释占位，确认不要再删。
    # =========================================================================
    def _build_root_view(self, win):
        # <hc:Window Title="{Binding WindowTitle}" Width="800" Height="600"
        #            MinWidth="800" MinHeight="600" ShowTitle="False">
        win.set_title("一键长草")
        win.set_size_request(800, 600)

        # --- <hc:Window.NonClientAreaContent> （自定义标题栏）---
        hb = Gtk.HeaderBar(); hb.set_show_title_buttons(True)
        #   <Grid Grid.Column="0">
        #     <Grid Grid.Column="0"> 两行更新信息（WindowVersionUpdateInfo / WindowResourceUpdateInfo）
        upd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.upd_ver_label = Gtk.Label(label=""); self.upd_ver_label.set_xalign(0); self.upd_ver_label.add_css_class("rainbow")
        self.upd_res_label = Gtk.Label(label=""); self.upd_res_label.set_xalign(0); self.upd_res_label.add_css_class("rainbow")
        upd.append(self.upd_ver_label); upd.append(self.upd_res_label)
        #     <hc:RunningBlock / TextBlock Text="{Binding WindowTitle}" />
        self.title_label = Gtk.Label(label="一键长草"); self.title_label.add_css_class("title")
        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        left.append(upd); left.append(self.title_label)
        #     （内联我们自己的）版本 + 只读设备地址
        self.ver_label = Gtk.Label(label="版本：…"); self.ver_label.add_css_class("dim-label")
        self.addr_label = Gtk.Label(label=self._current_address())
        self.addr_label.set_selectable(False); self.addr_label.set_can_focus(False)
        self.addr_label.add_css_class("dim-label")
        left.append(self.ver_label); left.append(self.addr_label)
        hb.set_title_widget(left)
        #   <Button Content="📌" Command="ToggleTopMostCommand" />  —— GTK4/Wayland 无窗口置顶，暂缺
        #   <Grid Grid.Column="1"> （内联我们自己的动作按钮；「停止」只在长草页底部，避免重复）
        b = Gtk.Button(label="检查更新"); b.connect("clicked", lambda _b: self.run_bg_update()); hb.pack_end(b)
        b = Gtk.Button(label="检测连接"); b.connect("clicked", self.on_check); hb.pack_end(b)
        win.set_titlebar(hb)

        # --- <Grid> 内容区 ---
        overlay = Gtk.Overlay()
        #   <Rectangle Fill="{DynamicResource RegionBrush}" />  （背景色，走主题）
        bg = Gtk.Box(); bg.add_css_class("region-bg"); overlay.set_child(bg)
        #   <Image Name="BgImage" Opacity="{BackgroundOpacity/100}" Source="{BackgroundImage}" />
        img = load_state().get("background_image")
        if img and os.path.exists(img):
            pic = Gtk.Picture.new_for_filename(img); pic.set_can_shrink(True)
            try: pic.set_opacity(max(0.0, min(1.0, int(load_state().get("background_opacity", 100)) / 100.0)))
            except Exception: pass
            bg.append(pic)
        #   <DockPanel><Grid>
        fg = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        fg.set_hexpand(True); fg.set_vexpand(True)
        #     <TabControl ItemsSource="{Binding Items}" Style="{StaticResource TabControlInLine}" />
        stack = Gtk.Stack(); stack.set_vexpand(True)
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(); switcher.set_stack(stack)
        switcher.set_halign(Gtk.Align.START); switcher.add_css_class("inline-tabs")
        for name, label, page in (("tasks", "一键长草", self.page_tasks()),
                                  ("combat", "自动战斗", self.page_copilot()),
                                  ("settings", "设置", self.page_settings())):
            stack.add_titled(page, name, label)
        fg.append(switcher)
        fg.append(stack)
        #     <ScrollViewer><StackPanel x:Name="AchievementGrowlPanel"/></ScrollViewer>  —— 成就浮层，暂缺
        #     <hc:GifImage .../>  —— 右下 GIF，暂缺
        #     （任务进度/日志在「一键长草」页的第三列，见 page_tasks；对齐官方 TaskQueueView 第 3 列）
        self.progress_rows = []
        overlay.add_overlay(fg)
        #   </Grid></DockPanel>
        win.set_child(overlay)
        # --- <hc:Interaction.Behaviors><hc:TaskbarRebuildBehavior/></hc:Interaction.Behaviors>  —— 暂缺

    def _maybe_run_daily(self):
        if load_state().get("run_daily_on_launch", False):
            self.logln("启动后自动运行一键日常 …")
            self.on_preset_daily(None)
            self.write_and_run(self.modules)
        return False

    def refresh_version(self):
        import threading
        def work():
            try:
                o = subprocess.run([MAA, "version"], capture_output=True, text=True, timeout=15)
                txt = " · ".join(o.stdout.split())
            except Exception as e:
                txt = f"版本读取失败: {e}"
            GLib.idle_add(self.ver_label.set_text, txt)
        threading.Thread(target=work, daemon=True).start()
        return False

    def on_close(self, win):
        try: self.save_queue()   # 关窗也存一次任务队列
        except Exception: pass
        try:
            st = load_state()
            st.update({"w": win.get_width(), "h": win.get_height()})
            save_state(st)
        except Exception: pass
        return False

    def _scroll(self, child):
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_propagate_natural_width(False); sw.set_propagate_natural_height(False)
        sw.set_vexpand(True); sw.set_child(child); return sw

    # ---------- 日志 / 运行 ----------
    def logln(self, s):
        import sys; line = f"[{datetime.datetime.now():%H:%M:%S}] {s.rstrip()}"; print(line, flush=True)
        if not hasattr(self, "logvbox"): return
        L = Gtk.Label(label=line); L.set_xalign(0); L.set_wrap(True)
        L.add_css_class("log-line")
        self.logvbox.append(L); self._log_labels.append(L)
        if len(self._log_labels) > 1500:
            old = self._log_labels.pop(0)
            try: self.logvbox.remove(old)
            except Exception: pass
        def _scroll():
            adj = self.log_scroll.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size()); return False
        GLib.idle_add(_scroll)

    def run_maa(self, argv):
        if self.proc: self.logln("已有任务在运行，先停止。"); return
        argv = ["-v"] + argv
        self.logln("$ maa " + " ".join(shlex.quote(a) for a in argv))
        env = dict(os.environ, PATH=os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", ""))
        try:
            import pty
            master, slave = pty.openpty()
            self.proc = subprocess.Popen([MAA] + argv, stdout=slave, stderr=slave, stdin=slave, close_fds=True, env=env)
            os.close(slave)
        except Exception as e:
            self.logln(f"启动失败: {e}"); return
        self._obuf = b""; self.btn_stop.set_sensitive(True)
        GLib.io_add_watch(master, GLib.IO_IN | GLib.IO_HUP, self.on_output)

    def on_output(self, src, cond):
        try: data = os.read(src, 4096)
        except OSError: data = b""
        if data:
            self._obuf += data
            while b"\n" in self._obuf:
                line, self._obuf = self._obuf.split(b"\n", 1)
                text = ANSI_RE.sub("", line.decode("utf-8", "replace"))
                self.logln(text); self.parse_progress(text)
            return True
        self.proc.wait()
        if self._obuf:
            text = ANSI_RE.sub("", self._obuf.decode("utf-8", "replace"))
            self.logln(text); self.parse_progress(text)
        rc = self.proc.returncode
        self.logln(f"—— 结束，退出码 {rc} ——")
        self.proc = None; self.btn_stop.set_sensitive(False)
        st = load_state()
        if st.get("notify_on_finish", False):
            self.notify("yuMAArin 任务结束", f"退出码 {rc}（{'成功' if rc == 0 else '异常'}）")
        if st.get("webhook_enabled") and str(st.get("webhook_url", "")).strip():
            when = st.get("webhook_when", "complete")
            if when == "both" or (when == "complete" and rc == 0) or (when == "error" and rc != 0):
                import threading
                threading.Thread(target=self.send_webhook,
                                 args=("yuMAArin 任务结束", f"退出码 {rc}"),
                                 daemon=True).start()
        return False

    def notify(self, title, body):
        try:
            self.send_notification(None, Gio.Notification.new(title))
            n = Gio.Notification.new(title); n.set_body(body)
            self.send_notification(None, n)
        except Exception as e:
            self.logln(f"[通知失败] {e}")

    def send_webhook(self, title, content):
        st = load_state()
        url = str(st.get("webhook_url", "")).strip()
        if not url: return
        import urllib.request
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tpl = st.get("webhook_body") or '{"title":"{title}","content":"{content}","time":"{time}"}'
        body = tpl.replace("{title}", title).replace("{content}", content).replace("{time}", t).encode("utf-8")
        headers = {}
        for line in (st.get("webhook_headers") or "").splitlines():
            if ":" in line:
                k, v = line.split(":", 1); headers[k.strip()] = v.strip()
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                GLib.idle_add(self.logln, f"[通知] Webhook 已发送（HTTP {getattr(r,'status',200)}）")
        except Exception as e:
            GLib.idle_add(self.logln, f"[通知] Webhook 发送失败: {e}")

    def _timer_tick(self):
        st = load_state()
        if st.get("timer_enabled") and st.get("timer_time"):
            now = datetime.datetime.now()
            hhmm = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            if hhmm == st["timer_time"] and self._timer_last != today:
                self._timer_last = today
                self.logln(f"== 定时到点（{hhmm}），执行一键日常 ==")
                self.on_preset_daily(None)
                if not self.proc: self.write_and_run(self.modules)
        return True

    def on_stop(self, _b):
        if self.proc: self.logln("停止中 …"); self.proc.terminate()

    def on_wait_stop(self, _b):
        if self.proc:
            self.logln("等待当前任务结束后停止 …")
            import signal
            try: self.proc.send_signal(signal.SIGINT)
            except Exception: self.proc.terminate()

    def _current_address(self):
        try:
            return json.load(open(PROFILE)).get("connection", {}).get("address") or DEFAULT_ADDR
        except Exception:
            return DEFAULT_ADDR

    def on_check(self, _b):
        addr = self._current_address()
        st = load_state()
        def work():
            env = dict(os.environ, PATH=os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", ""))
            def run(cmd):
                try:
                    o = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
                    return (o.stdout or o.stderr).strip() or "(无输出)"
                except Exception as e:
                    return f"出错: {e}"
            GLib.idle_add(self.logln, run([ADB, "connect", addr]))
            state = run([ADB, "-s", addr, "get-state"])
            GLib.idle_add(self.logln, state)
            if "device" not in state and st.get("retry_on_disconnected"):
                GLib.idle_add(self.logln, "连接异常，尝试重连 …")
                if st.get("allow_adb_restart"):
                    GLib.idle_add(self.logln, run([ADB, "kill-server"]))
                    GLib.idle_add(self.logln, run([ADB, "start-server"]))
                GLib.idle_add(self.logln, run([ADB, "connect", addr]))
                GLib.idle_add(self.logln, run([ADB, "-s", addr, "get-state"]))
        import threading; threading.Thread(target=work, daemon=True).start()

    # ---------- 自动更新 ----------
    def auto_check_update(self):
        if load_state().get("check_update_on_start", True): self.run_bg_update()
        return False
    def _proxy_env(self):
        import socket
        env = dict(os.environ)
        for k in ("http_proxy","https_proxy","all_proxy","HTTP_PROXY","HTTPS_PROXY","ALL_PROXY"):
            env.pop(k, None)   # 先清掉可能已失效的代理
        manual = str(load_state().get("proxy", "")).strip()
        proxy = manual or None
        if not proxy:
            for port in (7897, 38457):
                try:
                    s = socket.create_connection(("127.0.0.1", port), 0.5); s.close()
                    proxy = f"http://127.0.0.1:{port}"; break
                except Exception: pass
        if proxy:
            env.update(http_proxy=proxy, https_proxy=proxy, all_proxy=proxy,
                       HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy)
        # 覆盖 ~/.gitconfig 里写死的代理：有活代理用它，否则置空走直连
        env["GIT_CONFIG_COUNT"] = "2"
        env["GIT_CONFIG_KEY_0"] = "http.proxy";  env["GIT_CONFIG_VALUE_0"] = proxy or ""
        env["GIT_CONFIG_KEY_1"] = "https.proxy"; env["GIT_CONFIG_VALUE_1"] = proxy or ""
        return env, (proxy.split(":")[-1] if proxy else None)
    def run_bg_update(self):
        import threading
        if getattr(self, "_updating", False): self.logln("更新检查已在进行 …"); return
        self._updating = True
        threading.Thread(target=self._update_worker, daemon=True).start()
    def _update_worker(self):
        env, port = self._proxy_env()
        GLib.idle_add(self.logln, f"== 自动检查更新（代理: {port or '直连'}）==")
        for args, tag in ((["update","-t","0"], "MaaCore 与资源"), (["self","update"], "maa-cli 本体")):
            GLib.idle_add(self.logln, f"-- 检查{tag} --")
            try:
                p = subprocess.Popen([MAA]+args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
                for line in p.stdout:
                    if line.strip(): GLib.idle_add(self.logln, line.rstrip())
                p.wait()
            except Exception as e: GLib.idle_add(self.logln, f"[!] {tag} 检查失败: {e}")
        GLib.idle_add(self.logln, "== 更新检查完成 ==")
        self._updating = False

    # ---------- 任务页 ----------
    # ---------- 任务页：左列表(概览) / 右详情 ----------
    # ---- 表单通用件 ----
    def _form_header(self, spec):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top","bottom","start","end"): getattr(box, f"set_margin_{m}")(8)
        h = Gtk.Label(label=f'{spec["label"]}（{spec["type"]}）'); h.set_xalign(0); h.add_css_class("title-4")
        box.append(h)
        return box, {}

    def _labeled(self, box, label, widget, tip=None):
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4); lbox.set_size_request(220, -1)
        l = Gtk.Label(label=label); l.set_xalign(0); lbox.append(l)
        if tip:
            l.set_tooltip_text(tip)
            dot = Gtk.Label(label="ⓘ"); dot.add_css_class("info-dot")
            dot.set_tooltip_text(tip); dot.set_valign(Gtk.Align.CENTER); lbox.append(dot)
        r.append(lbox); r.append(widget); box.append(r)
        return r

    def _link_row(self, box, label, uri, text=None):
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pad = Gtk.Box(); pad.set_size_request(220, -1); r.append(pad)
        lb = Gtk.LinkButton.new_with_label(uri, text or label); lb.set_halign(Gtk.Align.START)
        r.append(lb); box.append(r)
        return r

    def _sub_row(self, box, indent=230):
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pad = Gtk.Box(); pad.set_size_request(indent, -1); r.append(pad)
        box.append(r)
        return r

    # ---- 各任务「官方形态」表单 ----
    def _form_recruit(self, spec):
        box, wids = self._form_header(spec)
        box.append(Gtk.Separator())
        # 1 每次执行时最大招募次数
        sp = make_widget("int", "4", None)
        self._labeled(box, "每次执行时最大招募次数", sp); wids["times"] = (sp, "int")
        # 2 自动使用加急许可
        cb = Gtk.CheckButton()
        self._labeled(box, "自动使用加急许可", cb, TIPS.get("expedite")); wids["expedite"] = (cb, "bool")
        # 3~6 自动确认 3/4/5/6 星（3/4 带招募时限 540 分）
        def _mk_confirm(lvl, dflt):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            c = Gtk.CheckButton(); c.set_active(dflt)
            lab = Gtk.Label(label=f"自动确认 {lvl} 星"); lab.set_xalign(0); lab.set_size_request(200, -1)
            r.append(c); r.append(lab)
            wids[f"confirm{lvl}"] = (c, "bool")
            if lvl in (3, 4):
                ts = make_widget("int", "540", None); ts.set_size_request(90, -1)
                r.append(Gtk.Label(label="招募时限(分钟)")); r.append(ts)
                wids[f"time{lvl}"] = (ts, "int")
                c.connect("toggled", lambda w, ts=ts: ts.set_sensitive(w.get_active()))
                ts.set_sensitive(dflt)
            box.append(r)
        for lvl, d in ((3, True), (4, True), (5, False), (6, False)): _mk_confirm(lvl, d)
        # 7 公招多选 Tag 的策略
        dd = make_widget("enum", "0", [("0","默认不选择额外 Tag"),("1","选择高星时总是选择三个 Tag"),("2","尽可能多地选且只选高星 Tag")])
        self._labeled(box, "公招多选 Tag 的策略", dd); wids["extra_tags_mode"] = (dd, "enum")
        # 8 3 星 Tag 倾向 / 9 自动刷新 3 星 Tags
        c2 = Gtk.CheckButton(); c2.set_active(True)
        self._labeled(box, "3 星 Tag 时的 Tag 倾向", c2, TIPS.get("first_tags")); wids["prefer_tags"] = (c2, "bool")
        c3 = Gtk.CheckButton(); c3.set_active(True)
        self._labeled(box, "自动刷新 3 星 Tags", c3); wids["refresh"] = (c3, "bool")
        # 10 3 星保留招聘许可（勾选 + 数值）
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        c4 = Gtk.CheckButton(); c4.set_active(False)
        lab = Gtk.Label(label="3 星保留招聘许可"); lab.set_xalign(0); lab.set_size_request(200, -1)
        sp2 = make_widget("int", "8", None); sp2.set_size_request(90, -1); sp2.set_sensitive(False)
        r.append(c4); r.append(lab); r.append(sp2)
        c4.connect("toggled", lambda w, s=sp2: s.set_sensitive(w.get_active()))
        if TIPS.get("level3_recruitment_permit_reserve"):
            d = Gtk.Label(label="ⓘ"); d.add_css_class("info-dot")
            d.set_tooltip_text(TIPS["level3_recruitment_permit_reserve"]); r.append(d)
        box.append(r); wids["reserve_enabled"] = (c4, "bool"); wids["reserve"] = (sp2, "int")
        # 11 无招聘许可仍刷新 Tags
        c5 = Gtk.CheckButton(); c5.set_active(True)
        self._labeled(box, "无招聘许可时继续尝试刷新 Tags", c5); wids["force_refresh"] = (c5, "bool")
        # 12 保留指定词条（勾选 + 输入）
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        c6 = Gtk.CheckButton()
        lab = Gtk.Label(label="保留指定词条"); lab.set_xalign(0); lab.set_size_request(200, -1)
        e = make_widget("str", "支援机械", None); e.set_hexpand(True); e.set_sensitive(False)
        r.append(c6); r.append(lab); r.append(e)
        c6.connect("toggled", lambda w, s=e: s.set_sensitive(w.get_active()))
        if TIPS.get("preserve_tags"):
            d = Gtk.Label(label="ⓘ"); d.add_css_class("info-dot")
            d.set_tooltip_text(TIPS["preserve_tags"]); r.append(d)
        box.append(r); wids["preserve_enabled"] = (c6, "bool"); wids["preserve"] = (e, "str")
        return box, wids

    def _sections(self, params):
        secs = []; cur = ("", [])
        for pr in params:
            if len(pr) == 2 and pr[0] == "group": secs.append(cur); cur = (pr[1], [])
            else: cur[1].append(pr)
        secs.append(cur)
        return [(t, rows) for t, rows in secs if rows]

    def _form_switchtheme(self, spec):
        box, wids = self._form_header(spec)
        self._render_param_rows(box, wids, spec["params"])
        return box, wids

    def _finish_sections(self, box, wids, spec, skip):
        secs = self._sections(spec["params"])
        self._render_one_section(box, wids, [r for r in secs[0][1] if r[0] not in skip] if secs else [])
        for t, rs in secs[1:]:
            gh = Gtk.Label(label=t); gh.set_xalign(0); gh.add_css_class("form-group"); box.append(gh)
            self._render_one_section(box, wids, rs)

    def _form_reclamation(self, spec):
        box, wids = self._form_header(spec); box.append(Gtk.Separator())
        secs = self._sections(spec["params"])
        if secs and secs[0][0]:
            gh = Gtk.Label(label=secs[0][0]); gh.set_xalign(0); gh.add_css_class("form-group"); box.append(gh)
        P = {p[0]: p for p in spec["params"] if len(p) >= 5}
        MODES = {"Tales": [("0", "无存档，通过进出关卡刷生息点数"), ("1", "有存档，通过组装支援道具刷生息点数")],
                 "RelaunchAnchor": [("16", "RA-1 精耕细作循环"), ("32", "RA-15：60 杀任务"), ("48", "RA-4：解锁区域")],
                 "Fire": [("0", "无存档"), ("1", "有存档")]}
        th = make_widget("enum", "Tales", P["theme"][4]); self._labeled(box, "生息演算主题", th); wids["theme"] = (th, "enum")
        md = Gtk.DropDown.new_from_strings([])
        def refresh(*_):
            opts = MODES.get(widget_value(th), MODES["Tales"])
            md.set_model(Gtk.StringList.new([o[1] for o in opts])); md._valmap = {o[1]: o[0] for o in opts}
            md.set_selected(0)
        th.connect("notify::selected", refresh); refresh()
        self._labeled(box, "模式", md); wids["mode"] = (md, "enum")
        self._finish_sections(box, wids, spec, ("theme", "mode"))
        return box, wids

    def _form_infrast(self, spec):
        box, wids = self._form_header(spec); box.append(Gtk.Separator())
        secs = self._sections(spec["params"])
        if secs and secs[0][0]:
            gh = Gtk.Label(label=secs[0][0]); gh.set_xalign(0); gh.add_css_class("form-group"); box.append(gh)
        P = {p[0]: p for p in spec["params"] if len(p) >= 5}
        md = make_widget("enum", "0", P["mode"][4]); self._labeled(box, "基建计划", md, TIPS.get("mode")); wids["mode"] = (md, "enum")
        fn = make_widget("enum", "UserDefined", [("UserDefined", "自定义"), ("153_layout_3_times_a_day.json", "153 一天 3 换"),
            ("153_layout_4_times_a_day.json", "153 一天 4 换"), ("243_layout_3_times_a_day.json", "243 一天 3 换"),
            ("243_layout_4_times_a_day.json", "243 一天 4 换"), ("333_layout_for_Orundum_3_times_a_day.json", "333 一天 3 换")])
        self._labeled(box, "内置配置", fn); wids["filename"] = (fn, "enum")
        dr = make_widget("enum", "Money", P["drones"][4]); self._labeled(box, "无人机用途", dr); wids["drones"] = (dr, "enum")
        # 自定义基建排班制作器（官方超链接 → 排班协议文档）
        self._link_row(box, "自定义基建排班制作器", "https://docs.maa.plus/zh-cn/protocol/base-scheduling-schema.html")
        # 换班设施（对齐官方：竖排列表，每行一个勾选）+ 全选 / 清空（两个半宽按钮）
        rooms = [("Mfg", "制造站"), ("Trade", "贸易站"), ("Power", "发电站"), ("Control", "控制中枢"),
                 ("Reception", "会客室"), ("Office", "办公室"), ("Dorm", "宿舍")]
        fac_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        hl = Gtk.Label(label="换班设施"); hl.set_xalign(0); hl.set_size_request(220, -1); fac_head.append(hl)
        if TIPS.get("facility"):
            d = Gtk.Label(label="ⓘ"); d.add_css_class("info-dot"); d.set_tooltip_text(TIPS["facility"]); fac_head.append(d)
        box.append(fac_head)
        fl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        fbox = Gtk.ListBox(); fbox.set_selection_mode(Gtk.SelectionMode.NONE); fbox.add_css_class("plain")
        cbs = {}
        for key, name in rooms:
            row = Gtk.ListBoxRow(); cb = Gtk.CheckButton(label=name); cb.set_active(True)
            row.set_child(cb); fbox.append(row); cbs[key] = cb
        fl.append(fbox)
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        sel = Gtk.Button(label="全选"); sel.set_hexpand(True)
        clr = Gtk.Button(label="清空"); clr.set_hexpand(True)
        sel.connect("clicked", lambda _b: [c.set_active(True) for c in cbs.values()])
        clr.connect("clicked", lambda _b: [c.set_active(False) for c in cbs.values()])
        btns.append(sel); btns.append(clr); fl.append(btns); box.append(fl)
        wids["__facility__"] = (cbs, "rooms")
        self._finish_sections(box, wids, spec, ("mode", "filename", "drones", "facility"))
        return box, wids

    def _form_roguelike(self, spec):
        box, wids = self._form_header(spec); box.append(Gtk.Separator())
        secs = self._sections(spec["params"])
        if secs and secs[0][0]:
            gh = Gtk.Label(label=secs[0][0]); gh.set_xalign(0); gh.add_css_class("form-group"); box.append(gh)
        P = {p[0]: p for p in spec["params"] if len(p) >= 5}
        MODES = {
          "default": [("0","刷等级，尽可能稳定地打更多层数"),("1","刷源石锭，投资完成后自动退出"),
                      ("4","刷开局，刷取热水壶或精二干员开局"),("6","刷月度小队，尽可能稳定地打更多层数"),
                      ("7","刷深入调查，尽可能稳定地打更多层数")],
          "Sami": [("5","刷坍缩范式")], "JieGarden": [("20001","刷常乐节点，第一层进洞，找不到就重开")],
          "BlackFlow": [("0","刷等级，快速飞三层"),("1","刷源石锭，投资完成后自动退出"),("30001","刷襁褓动物")]}
        th = make_widget("enum", "Phantom", P["theme"][4]); self._labeled(box, "肉鸽主题", th); wids["theme"] = (th, "enum")
        mo = Gtk.DropDown.new_from_strings([])
        def refresh(*_):
            t = widget_value(th); opts = list(MODES["default"]) if t != "BlackFlow" else list(MODES["BlackFlow"])
            opts += MODES.get(t, [])
            mo.set_model(Gtk.StringList.new([o[1] for o in opts])); mo._valmap = {o[1]: o[0] for o in opts}
            mo.set_selected(0)
        th.connect("notify::selected", refresh); refresh()
        self._labeled(box, "策略", mo); wids["mode"] = (mo, "enum")
        self._finish_sections(box, wids, spec, ("theme", "mode"))
        return box, wids

    def _form_startup(self, spec):
        box, wids = self._form_header(spec)
        box.append(Gtk.Separator())
        sg = Gtk.CheckButton(); sg.set_active(True)
        self._labeled(box, "是否启动客户端", sg); wids["start_game_enabled"] = (sg, "bool")
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        c = Gtk.CheckButton()
        lab = Gtk.Label(label="账号切换"); lab.set_xalign(0); lab.set_size_request(200, -1)
        e = make_widget("str", "", None); e.set_hexpand(True); e.set_sensitive(False)
        r.append(c); r.append(lab); r.append(e)
        c.connect("toggled", lambda w, s=e: s.set_sensitive(w.get_active()))
        tip = TIPS.get("account_name")
        if tip:
            d = Gtk.Label(label="ⓘ"); d.add_css_class("info-dot"); d.set_tooltip_text(tip); r.append(d)
        box.append(r); wids["account_switch"] = (c, "bool"); wids["account_name"] = (e, "str")
        return box, wids

    def _collect_startup(self, wids, spec=None):
        wv = lambda k: widget_value(wids[k][0])
        return {"start_game_enabled": bool(wv("start_game_enabled")),
                "account_name": str(wv("account_name")) if wv("account_switch") else ""}

    def _form_fight(self, spec):
        box, wids = self._form_header(spec)
        box.append(Gtk.Separator())
        P = {p[0]: p for p in spec["params"] if len(p) >= 5}
        def gnum(key, label, tip=None):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            c = Gtk.CheckButton()
            lab = Gtk.Label(label=label); lab.set_xalign(0); lab.set_size_request(200, -1)
            sp = make_widget("int", "0", None); sp.set_size_request(90, -1); sp.set_sensitive(False)
            r.append(c); r.append(lab); r.append(sp)
            c.connect("toggled", lambda w, s=sp: s.set_sensitive(w.get_active()))
            if tip:
                d = Gtk.Label(label="ⓘ"); d.add_css_class("info-dot"); d.set_tooltip_text(tip); r.append(d)
            box.append(r); wids[key + "_enabled"] = (c, "bool"); wids[key] = (sp, "int")
        gnum("medicine", "使用药剂")
        gnum("stone", "使用源石")
        gnum("times", "指定次数")
        # 官方：勾选「无限吃 N 天内过期的理智药」+ 独立数值「只吃游戏内显示不足 N 天的理智药」（默认 2）
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        c = Gtk.CheckButton()
        lab = Gtk.Label(label="无限吃 N 天内过期的理智药"); lab.set_xalign(0); lab.set_size_request(200, -1)
        nl = Gtk.Label(label="只吃不足 N 天的理智药"); nl.add_css_class("dim-label")
        sp = make_widget("int", "2", None); sp.set_size_request(80, -1); sp.set_sensitive(False)
        r.append(c); r.append(lab); r.append(nl); r.append(sp)
        c.connect("toggled", lambda w, s=sp: s.set_sensitive(w.get_active()))
        if TIPS.get("medicine_expire_days"):
            d = Gtk.Label(label="ⓘ"); d.add_css_class("info-dot"); d.set_tooltip_text(TIPS["medicine_expire_days"]); r.append(d)
        box.append(r); wids["medicine_expire_days_enabled"] = (c, "bool"); wids["medicine_expire_days"] = (sp, "int")
        # 指定材料（勾选 + 掉落表）
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        c = Gtk.CheckButton()
        lab = Gtk.Label(label="指定材料"); lab.set_xalign(0); lab.set_size_request(200, -1)
        kv = make_widget("kv", {}, None, {"key_label": "物品ID(如 30011)", "val_label": "目标数量", "val_type": "int"})
        kv.set_hexpand(True); kv.set_sensitive(False)
        r.append(c); r.append(lab); r.append(kv)
        c.connect("toggled", lambda w, s=kv: s.set_sensitive(w.get_active()))
        if TIPS.get("drops"):
            d = Gtk.Label(label="ⓘ"); d.add_css_class("info-dot"); d.set_tooltip_text(TIPS["drops"]); r.append(d)
        box.append(r); wids["drops_enabled"] = (c, "bool"); wids["drops"] = (kv, "kv")
        # 关卡 / 代理倍率 / 博朗台
        st = make_widget("enum", "", P["stage"][4]); self._labeled(box, "关卡", st, TIPS.get("stage")); wids["stage"] = (st, "enum")
        se = make_widget("enum", "0", P["series"][4]); self._labeled(box, "代理倍率", se, TIPS.get("series")); wids["series"] = (se, "enum")
        dg = Gtk.CheckButton(); self._labeled(box, "博朗台模式", dg, TIPS.get("DrGrandet")); wids["DrGrandet"] = (dg, "bool")
        return box, wids

    def _collect_fight(self, wids, spec=None):
        wv = lambda k: widget_value(wids[k][0])
        p = {"stage": wv("stage"), "series": int(wv("series")), "DrGrandet": bool(wv("DrGrandet"))}
        if wv("medicine_enabled"): p["medicine"] = int(wv("medicine"))
        if wv("stone_enabled"): p["stone"] = int(wv("stone"))
        if wv("times_enabled"): p["times"] = int(wv("times"))
        if wv("medicine_expire_days_enabled"): p["medicine_expire_days"] = int(wv("medicine_expire_days"))
        if wv("drops_enabled"):
            d = wv("drops")
            if d: p["drops"] = d
        return p

    def _collect_recruit(self, wids, spec=None):
        wv = lambda k: widget_value(wids[k][0])
        confirm = [lvl for lvl in (3, 4, 5, 6) if wv(f"confirm{lvl}")]
        params = {"select": [3, 4, 5, 6], "confirm": confirm, "times": int(wv("times")),
                  "expedite": bool(wv("expedite")), "refresh": bool(wv("refresh")),
                  "extra_tags_mode": int(wv("extra_tags_mode")), "set_time": True, "skip_robot": True}
        rtime = {}
        if wv("confirm3"): rtime["3"] = int(wv("time3"))
        if wv("confirm4"): rtime["4"] = int(wv("time4"))
        if rtime: params["recruitment_time"] = rtime
        if wv("reserve_enabled"): params["level3_recruitment_permit_reserve"] = int(wv("reserve"))
        if wv("preserve_enabled"):
            params["preserve_tags"] = [x.strip() for x in str(wv("preserve")).split(";") if x.strip()]
        return params

    def _render_param_rows(self, box, wids, params, skip=(), title=None):
        for sec_title, sec_rows in self._sections(params):
            rows = [pr for pr in sec_rows if pr[0] not in skip]
            if not rows: continue
            head = title if title and sec_title == "" else sec_title
            if head:
                gh = Gtk.Label(label=head); gh.set_xalign(0); gh.add_css_class("form-group")
                box.append(gh)
                title = None
            self._render_one_section(box, wids, rows)
        return box

    def _render_one_section(self, box, wids, params):
        for pr in params:
            k, lab, kind, dflt, choices = pr[:5]
            extra = pr[5] if len(pr) > 5 else None
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            lbox.set_size_request(220, -1)
            l = Gtk.Label(label=lab); l.set_xalign(0); lbox.append(l)
            tip = TIPS.get(k)
            if tip:
                l.set_tooltip_text(tip)
                dot = Gtk.Label(label="ⓘ"); dot.add_css_class("info-dot")
                dot.set_tooltip_text(tip); dot.set_valign(Gtk.Align.CENTER)
                lbox.append(dot)
            r.append(lbox)
            w = make_widget(kind, dflt, choices, extra)
            if kind in ("kv", "rows", "slist", "text"): w.set_hexpand(True)
            r.append(w)
            wids[k] = (w, kind)
            box.append(r)

    def _build_form(self, spec):
        if spec.get("custom"):
            return getattr(self, f"_form_{spec['custom']}")(spec)
        box, wids = self._form_header(spec)
        self._render_param_rows(box, wids, spec["params"])
        if not spec["params"]:
            box.append(Gtk.Label(label="（本任务无可调参数）"))
        return box, wids

    def page_tasks(self):
        # 布局对齐官方 TaskQueueView：左窄列=任务卡列表（底部一行：添加任务菜单/全选/反选）；
        # 右侧=选中任务的设置详情 + 底部居中「开始/停止/等待并停止」。
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top","bottom","start","end"): getattr(box, f"set_margin_{m}")(8)

        hp = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL); hp.set_vexpand(True); hp.set_position(220)
        hp.set_shrink_start_child(False)   # 左窄列不可拖到最小宽度以下

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.set_size_request(210, -1)     # 对齐官方任务列宽 210
        left.add_css_class("task-column")
        for m in ("top","bottom","start","end"): getattr(left, f"set_margin_{m}")(4)
        self.mod_list = Gtk.ListBox(); self.mod_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.mod_list.set_size_request(196, -1)
        self.mod_list.connect("row-selected", self.on_select_module)
        lscroll = Gtk.ScrolledWindow(); lscroll.set_vexpand(True); lscroll.set_child(self.mod_list)
        left.append(lscroll)
        lb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        mb = Gtk.MenuButton(label="添加任务")
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        pv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for s in TASKS:
            b = Gtk.Button(label=s["label"])
            b.connect("clicked", lambda _b, t=s["type"], p=pop: (p.popdown(), self.add_module(t, select=True)))
            pv.append(b)
        psw = Gtk.ScrolledWindow(); psw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        psw.set_propagate_natural_height(True); psw.set_max_content_height(460)
        psw.set_propagate_natural_width(True); psw.set_child(pv)
        pop.set_child(psw); mb.set_popover(pop); lb.append(mb)
        b = Gtk.Button(label="全选"); b.connect("clicked", lambda _b: self.set_all(True)); lb.append(b)
        b = Gtk.Button(label="反选"); b.connect("clicked", lambda _b: self.invert()); lb.append(b)
        left.append(lb)
        hp.set_start_child(left)

        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.detail = Gtk.ScrolledWindow(); self.detail.set_vexpand(True); mid.append(self.detail)
        # 「显示游戏窗口」：勾上→跑前打开 Waydroid 窗口看着；不勾→静默后台跑（状态记忆）
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.show_win = Gtk.CheckButton(label="显示游戏窗口")
        self.show_win.set_active(bool(load_state().get("show_game_window", False)))
        self.show_win.connect("toggled", self._on_show_win_toggle)
        bar.append(self.show_win)
        sdot = Gtk.Label(label="ⓘ"); sdot.add_css_class("info-dot"); sdot.set_valign(Gtk.Align.CENTER)
        sdot.set_tooltip_text(
            "显示游戏窗口：勾选＝立即打开 Waydroid 窗口，且以后每次运行前自动打开（看着跑）；\n"
            "取消＝以后静默后台跑。已打开的窗口请点它自己的 × 关闭（Waydroid 无法命令行隐藏）。")
        bar.append(sdot)
        self._scrcpy_proc = None; self._waydroid_proc = None
        self.tg_scrcpy = Gtk.ToggleButton()
        sbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._scrcpy_lbl = Gtk.Label(label="监工(scrcpy)"); sbox.append(self._scrcpy_lbl)
        sdot2 = Gtk.Label(label="ⓘ"); sdot2.add_css_class("info-dot"); sdot2.set_valign(Gtk.Align.CENTER)
        sdot2.set_tooltip_text(
            "监工：用 scrcpy 打开小窗镜像（可手动操作）；再点一下＝关掉。关掉窗口不影响任务。\n"
            "已限负载（720p/15fps/2Mbps/无音频）。⚠ 别频繁反复开关：scrcpy 解码压在核显上，\n"
            "曾出现 Intel 核显挂死导致整机卡死；长时间「看着跑」更推荐用左边的「显示游戏窗口」\n"
            "（Waydroid 原生窗口，少一路解码，更省）。")
        sbox.append(sdot2); self.tg_scrcpy.set_child(sbox)
        self.tg_scrcpy.connect("toggled", self._toggle_scrcpy); bar.append(self.tg_scrcpy)
        bar.set_halign(Gtk.Align.START)
        mid.append(bar)
        bb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10); bb.set_halign(Gtk.Align.CENTER)
        STOPTIP = ("停止：立即停止（发终止信号，可能打断当前操作）。\n"
                   "等待并停止：等当前这一步 / 这场战斗结束后再停，不继续后续任务（更稳妥）。")
        for lab, fn, cls in [("开始", self.on_run_selected, "suggested-action"),
                             ("停止", self.on_stop, None),
                             ("等待并停止", self.on_wait_stop, None)]:
            b = Gtk.Button(); b.set_size_request(110, 46)
            if cls: b.add_css_class(cls)
            if lab == "等待并停止":                          # ⓘ 放进按钮内部（文字 + ⓘ）
                hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                hb2.append(Gtk.Label(label=lab))
                idot = Gtk.Label(label="ⓘ"); idot.add_css_class("info-dot"); idot.set_valign(Gtk.Align.CENTER)
                idot.set_tooltip_text(STOPTIP); hb2.append(idot); b.set_child(hb2)
            else:
                b.set_label(lab)
            if lab == "停止":
                self.btn_stop = b; b.set_sensitive(False)   # 底部这枚才是运行期的停止键
            b.connect("clicked", fn); bb.append(b)
        mid.append(bb)

        # 第三列（对齐官方 TaskQueueView 第 3 列）：运行日志（任务状态/耗时改在左侧任务卡上显示）
        lframe = Gtk.Frame(label="运行日志")
        self.log_scroll = Gtk.ScrolledWindow(); self.log_scroll.set_vexpand(True)
        self.log_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.logvbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for m in ("top", "bottom", "start", "end"): getattr(self.logvbox, f"set_margin_{m}")(4)
        self._log_labels = []
        self.log_scroll.set_child(self.logvbox)
        lframe.set_child(self.log_scroll)

        # 中间 = 设置详情 + 按钮；外层 = 左列 | (中列 | 日志列)
        inner = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL); inner.set_vexpand(True)
        inner.set_position(340); inner.set_shrink_start_child(False)
        inner.set_start_child(mid); inner.set_end_child(lframe)
        hp.set_position(214); hp.set_end_child(inner)

        box.append(hp)
        self.modules = []
        saved = self.load_queue()
        if saved:
            for st in saved:
                if not any(s["type"] == st.get("type") for s in TASKS): continue
                m = self.add_module(st["type"])
                if m: self._apply_mod_state(m, st)
            if self.modules:
                self.mod_list.select_row(self.modules[0]["row"])
            self.logln(f"已恢复上次的任务队列（{len(self.modules)} 个模块）")
        else:
            self.on_preset_daily(None)
        return box

    def add_module(self, type_name, select=False):
        spec = next((s for s in TASKS if s["type"] == type_name), None)
        if not spec: return None
        form, wids = self._build_form(spec)
        row = Gtk.ListBoxRow(); row.add_css_class("task-row")
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for m in ("top","bottom","start","end"): getattr(hb, f"set_margin_{m}")(6)
        cb = Gtk.CheckButton(); cb.set_active(True); hb.append(cb)
        lab = Gtk.Label(label=spec["label"]); lab.set_xalign(0); lab.set_hexpand(True); hb.append(lab)
        slab = Gtk.Label(label=""); slab.add_css_class("dim-label"); slab.set_xalign(1)
        hb.append(slab)
        gear = Gtk.Button(label="⚙"); gear.add_css_class("task-gear"); gear.add_css_class("flat")
        gear.set_tooltip_text("任务设置（右键更多）")
        gear.connect("clicked", lambda _b, r=row: self.mod_list.select_row(r))
        hb.append(gear); row.set_child(hb)
        mod = dict(spec=spec, form=form, wids=wids, row=row, enabled=cb, label=lab, slab=slab, name=spec["label"])
        self.modules.append(mod); self.mod_list.append(row)
        gest = Gtk.GestureClick(); gest.set_button(3)
        gest.connect("pressed", lambda g, n, x, y, r=row: self.on_row_menu(r))
        row.add_controller(gest)
        # 拖拽排序（对齐官方 dd:DragDrop）
        mid = str(self._mod_seq); self._mod_seq += 1; mod["id"] = mid
        src = Gtk.DragSource(); src.set_actions(Gdk.DragAction.MOVE)
        src.connect("prepare", lambda s, x, y, mid=mid: Gdk.ContentProvider.new_for_value(mid))
        row.add_controller(src)
        dt = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        dt.connect("drop", lambda t, v, x, y, r=row: self.on_row_drop(v, r))
        row.add_controller(dt)
        if select: self.mod_list.select_row(row)
        return mod

    def on_row_drop(self, value, row):
        mid = value.get_string() if hasattr(value, "get_string") else str(value)
        src_mod = next((m for m in self.modules if m.get("id") == mid), None)
        dst_mod = next((m for m in self.modules if m["row"] is row), None)
        if not src_mod or not dst_mod or src_mod is dst_mod: return False
        src_i = self.modules.index(src_mod); dst_i = self.modules.index(dst_mod)
        self.modules.pop(src_i)
        # 下拖→插到目标之后；上拖→插到目标之前（都取移除前的目标下标），保证拖到末尾即成末项
        self.modules.insert(dst_i, src_mod)
        for m in self.modules: self.mod_list.remove(m["row"])
        for m in self.modules: self.mod_list.append(m["row"])
        self.mod_list.select_row(src_mod["row"])
        self.on_select_module(self.mod_list, src_mod["row"])   # 重建后确保右详情不空
        self.logln(f"已调整顺序：{src_mod.get('name', src_mod['spec']['label'])}")
        return True

    def set_widget_value(self, w, kind, value):
        if w is None: return
        if hasattr(w, "_set"): w._set(value); return
        if kind == "bool": w.set_active(bool(value))
        elif kind in ("int", "float"):
            try: w.set_value(float(value))
            except Exception: w.set_value(0)
        elif kind == "enum":
            vm = getattr(w, "_valmap", None); lab = None
            if vm:   # _valmap: 显示文案 -> 值；这里按「值」反查文案
                for l, v in vm.items():
                    if str(v) == str(value): lab = l; break
            if lab is None: lab = str(value)
            model = w.get_model()
            for i in range(model.get_n_items()):
                if model.get_string(i) == lab: w.set_selected(i); break
        elif kind == "json":
            try: w.set_text("" if value in (None, "", [], {}) else json.dumps(value, ensure_ascii=False))
            except Exception: w.set_text(str(value))
        else: w.set_text(str(value))

    def set_param(self, mod, key, value):
        w, kind = mod["wids"].get(key, (None, None))
        self.set_widget_value(w, kind, value)

    # ---- 任务队列持久化（重启不丢设置）----
    def _mod_state(self, m):
        vals = {}
        for k, (w, kind) in m["wids"].items():
            if k == "__facility__" and isinstance(w, dict):
                vals[k] = {room: cb.get_active() for room, cb in w.items()}
            elif isinstance(w, dict):
                continue
            else:
                try: vals[k] = widget_value(w)
                except Exception: pass
        return {"type": m["spec"]["type"], "name": m.get("name", m["spec"]["label"]),
                "enabled": m["enabled"].get_active(), "vals": vals}

    def _apply_mod_state(self, m, st):
        for k, v in (st.get("vals") or {}).items():
            if k == "__facility__" and k in m["wids"] and isinstance(m["wids"][k][0], dict):
                cbs = m["wids"][k][0]
                for room, on in (v or {}).items():
                    if room in cbs: cbs[room].set_active(bool(on))
            else:
                self.set_param(m, k, v)
        m["enabled"].set_active(bool(st.get("enabled", True)))
        nm = st.get("name")
        if nm: m["name"] = nm; m["label"].set_text(nm)

    def save_queue(self):
        try:
            os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump({"modules": [self._mod_state(m) for m in self.modules]}, f,
                          ensure_ascii=False, indent=2)
        except Exception as e:
            self.logln(f"[队列保存失败] {e}")

    def load_queue(self):
        try:
            data = json.load(open(QUEUE_FILE, encoding="utf-8"))
            return data.get("modules") or None
        except Exception:
            return None

    def set_all(self, v):
        for m in self.modules: m["enabled"].set_active(v)

    def invert(self):
        for m in self.modules: m["enabled"].set_active(not m["enabled"].get_active())

    def on_row_menu(self, row):
        m = next((x for x in self.modules if x["row"] is row), None)
        if not m: return
        pop = Gtk.Popover()
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for lab, fn in [("立即执行一次", lambda: self.run_once(m)),
                        ("复制此模块", lambda: self.copy_module(m)),
                        ("重命名", lambda: self.rename_module(m)),
                        ("上移", lambda: self.move_module(m, -1)),
                        ("下移", lambda: self.move_module(m, 1)),
                        ("删除", lambda: self.del_module(m))]:
            b = Gtk.Button(label=lab)
            b.connect("clicked", lambda _b, f=fn, p=pop: (p.popdown(), f()))
            vb.append(b)
        pop.set_child(vb); pop.set_parent(row); pop.popup()

    def copy_module(self, m):
        nm = self.add_module(m["spec"]["type"], select=True)
        for k, (w, kind) in m["wids"].items():
            nw = nm["wids"].get(k, (None, None))[0]
            self.set_widget_value(nw, kind, widget_value(w))

    def del_module(self, m):
        self.modules.remove(m); self.mod_list.remove(m["row"]); self.detail.set_child(None)

    def rename_module(self, m):
        win = Gtk.Window(transient_for=self.get_active_window()); win.set_title("重命名模块")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for s in ("top","bottom","start","end"): getattr(box, f"set_margin_{s}")(10)
        e = Gtk.Entry(); e.set_text(m["name"]); box.append(e)
        ob = Gtk.Button(label="确定")
        def ok(_b):
            name = e.get_text().strip()
            if name:
                m["name"] = name; m["label"].set_text(name)
            win.close()
        ob.connect("clicked", ok); box.append(ob)
        win.set_child(box); win.present()

    def run_once(self, m):
        self.write_and_run([m])

    def on_add_task(self, _b):
        item = self.add_type.get_selected_item()
        if not item: return
        s = item.get_string(); t = s[s.rfind("(") + 1:-1]
        self.add_module(t, select=True)

    def _selected(self):
        row = self.mod_list.get_selected_row()
        return next((m for m in self.modules if m["row"] is row), None)

    def on_del_task(self, _b):
        m = self._selected()
        if not m: return
        self.modules.remove(m); self.mod_list.remove(m["row"]); self.detail.set_child(None)

    def on_move(self, delta):
        m = self._selected()
        if m: self.move_module(m, delta)

    def move_module(self, m, delta):
        i = self.modules.index(m); j = i + delta
        if j < 0 or j >= len(self.modules): return
        self.modules[i], self.modules[j] = self.modules[j], self.modules[i]
        for x in self.modules: self.mod_list.remove(x["row"])
        for x in self.modules: self.mod_list.append(x["row"])
        self.mod_list.select_row(m["row"])
        self.on_select_module(self.mod_list, m["row"])

    def on_select_module(self, _lb, row):
        m = next((x for x in self.modules if x["row"] is row), None)
        self.detail.set_child(m["form"] if m else None)

    def _collect_generic(self, spec, wids, skip=()):
        p = {}
        for pr in spec["params"]:
            if len(pr) == 2 and pr[0] == "group": continue
            k, kind = pr[0], pr[2]
            if k in skip: continue
            w, _ = wids[k]; v = coerce(kind, widget_value(w))
            if v is None: continue
            p[k] = v
        return p

    def _collect_reclamation(self, wids, spec):
        p = self._collect_generic(spec, wids, skip=("theme", "mode"))
        p["theme"] = widget_value(wids["theme"][0]); p["mode"] = int(widget_value(wids["mode"][0]))
        return p

    def _collect_infrast(self, wids, spec):
        p = self._collect_generic(spec, wids, skip=("mode", "filename", "drones", "facility"))
        p["mode"] = int(widget_value(wids["mode"][0])); p["drones"] = widget_value(wids["drones"][0])
        fn = widget_value(wids["filename"][0])
        if p.get("mode") == 10000 and fn and fn != "UserDefined": p["filename"] = fn
        cbs = wids["__facility__"][0]
        p["facility"] = [k for k, cb in cbs.items() if cb.get_active()]
        return p

    def _collect_roguelike(self, wids, spec):
        p = self._collect_generic(spec, wids, skip=("theme", "mode"))
        p["theme"] = widget_value(wids["theme"][0]); p["mode"] = int(widget_value(wids["mode"][0]))
        return p

    def collect_params(self, spec, wids):
        if spec.get("custom"):
            return getattr(self, f"_collect_{spec['custom']}")(wids, spec)
        return self._collect_generic(spec, wids)

    def write_and_run(self, mods):
        # 全局项（设置→游戏 / 三方服务）统一下发，避免与长草逐任务设置重复
        game = load_state().get("game", {}) or {}
        client = game.get("client_type") or "Official"
        server = SERVER_OF_CLIENT.get(client, "CN")
        tasks = []
        for m in mods:
            if not m["enabled"].get_active(): continue
            typ = m["spec"]["type"]
            params = self.collect_params(m["spec"], m["wids"])
            if typ == "Infrast" and "threshold" in params:
                try: params["threshold"] = float(params["threshold"]) / 100.0
                except Exception: params.pop("threshold", None)
            if typ in ("StartUp", "CloseDown", "Fight"):
                params["client_type"] = client
            if typ in ("Fight", "Recruit"):
                params["server"] = server
                if game.get("report_to_penguin"):
                    params["report_to_penguin"] = True
                    if game.get("penguin_id"): params["penguin_id"] = game["penguin_id"]
                if game.get("report_to_yituliu"):
                    params["report_to_yituliu"] = True
                    if game.get("yituliu_id"): params["yituliu_id"] = game["yituliu_id"]
            t = {"name": m.get("name", m["spec"]["label"]), "type": typ}
            if params: t["params"] = params
            tasks.append(t)
        if not tasks: self.logln("没有勾选任何模块"); return
        os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            # 不写顶层 startup/closedown：让 StartUp / CloseDown「任务」自己驱动
            # （maa-cli：顶层 closedown=false 会让 CloseDown 任务失效 → 关闭游戏不执行）
            json.dump({"client_type": client, "tasks": tasks},
                      f, ensure_ascii=False, indent=2)
        self.logln(f"已写入 {TASKS_FILE}（{len(tasks)} 个任务）")
        self.save_queue()            # 开跑即存一次，防止重启丢设置
        self._maybe_show_game_window()
        self.set_progress(mods)
        self.run_maa(["run","--batch","ui"])

    def _add_progress_row(self, name, typ, mod=None):
        # 不再单独显示进度列表：状态/耗时直接写回左侧任务卡（按唯一 mod 绑定，避免重名串台）
        rec = {"name": name, "type": typ, "status": "待运行", "start": None, "dur": "", "mod": mod}
        self.progress_rows.append(rec)
        return rec

    def _render_progress(self):
        mark = {"待运行": "○", "运行中": "▶", "完成": "✔", "失败": "✘"}
        row_cls = {"运行中": "inprogress", "完成": "completed", "失败": "error", "跳过": "skipped"}
        for r in self.progress_rows:
            mod = r.get("mod")
            if not mod: continue
            for c in ("inprogress", "completed", "error", "skipped"):
                mod["row"].remove_css_class(c)
            c2 = row_cls.get(r["status"])
            if c2: mod["row"].add_css_class(c2)
            slab = mod.get("slab")
            if slab:
                txt = mark.get(r["status"], "○") + " " + r["status"]
                if r.get("dur"): txt += f" {r['dur']}"
                slab.set_text(txt)

    def set_progress(self, mods):
        self.progress_rows = []
        names = []
        for m in mods:
            if not m["enabled"].get_active(): continue
            nm = m.get("name", m["spec"]["label"])
            self._add_progress_row(nm, m["spec"]["type"], m); names.append(nm)
        # 未勾选的模块：清掉可能残留的状态
        for m in mods:
            if not m["enabled"].get_active():
                for c in ("inprogress", "completed", "error", "skipped"):
                    m["row"].remove_css_class(c)
                if m.get("slab"): m["slab"].set_text("")
        if names: self.logln("任务队列：" + " → ".join(names))

    def parse_progress(self, line):
        if not getattr(self, "progress_rows", None): return
        s = line.strip()
        if s.endswith("AllTasksCompleted"):
            for r in self.progress_rows:
                if r["status"] in ("运行中", "待运行"): r["status"] = "完成"
            self._render_progress(); return
        m = re.search(r"\]\s*([A-Za-z0-9_]+)\s+(Start|Completed)\s*$", s)
        if m:
            typ, ev = m.group(1), m.group(2)
            want = "待运行" if ev == "Start" else "运行中"
            row = next((r for r in self.progress_rows if r["type"] == typ and r["status"] == want), None)
            if row:
                if ev == "Start":
                    row["status"] = "运行中"; row["start"] = datetime.datetime.now()
                else:
                    row["status"] = "完成"
                    if row.get("start"):
                        d = int((datetime.datetime.now() - row["start"]).total_seconds())
                        row["dur"] = f"{d}s"
                self._render_progress()
            return
        m = re.match(r"^\[(.+?)\]\s+(\d{2}:\d{2}:\d{2})\s*-\s*(\d{2}:\d{2}:\d{2})\s*\(([^)]*)\)\s*(\S+)", s)
        if m:
            name, st, en, dur, status = m.groups()
            row = next((r for r in self.progress_rows if r["name"] == name), None)
            if row:
                row["status"] = {"Completed": "完成", "Failed": "失败", "Error": "失败"}.get(status, status)
                row["dur"] = str(dur)
                self._render_progress()

    def _save_show_win(self, on):
        try:
            st = load_state(); st["show_game_window"] = bool(on); save_state(st)
        except Exception: pass

    def _on_show_win_toggle(self, btn):
        on = btn.get_active()
        self._save_show_win(on)
        if on: self._open_waydroid()   # 勾上即刻打开，之后每次运行前也会自动打开

    def _maybe_show_game_window(self):
        if not load_state().get("show_game_window", False):
            self.logln("静默运行（不打开 Waydroid 窗口）"); return
        try:
            import shutil
            exe = shutil.which("waydroid") or "/usr/bin/waydroid"
            subprocess.Popen([exe, "show-full-ui"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            self.logln("已打开 Waydroid 窗口（看着跑）")
        except Exception as e:
            self.logln(f"[打开 Waydroid 窗口失败] {e}")

    def _kill_proc(self, proc):
        # 先优雅（SIGINT，scrcpy 会自行清理设备端 server），3s 后仍在则强杀
        if not proc or proc.poll() is not None: return
        import signal, threading, time
        try: os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        except Exception:
            try: proc.terminate()
            except Exception: pass
        def _force():
            time.sleep(3)
            if proc.poll() is None:
                try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    try: proc.kill()
                    except Exception: pass
        threading.Thread(target=_force, daemon=True).start()

    def _toggle_scrcpy(self, btn):
        if btn.get_active():
            import shutil
            cand = os.path.expanduser("~/.local/bin/scrcpy")
            exe = cand if os.path.exists(cand) else (shutil.which("scrcpy") or "/usr/bin/scrcpy")
            if not os.path.exists(exe) and not shutil.which(exe):
                self.logln("未安装 scrcpy（已放 ~/.local/bin/scrcpy 或 sudo apt install scrcpy）")
                btn.set_active(False); return
            addr = self._current_address()
            try:
                env = dict(os.environ, PATH=os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", ""))
                # 降负载（核显容易挂）：720p / 15fps / 2Mbps / 无音频
                self._scrcpy_proc = subprocess.Popen(
                    [exe, "-s", addr, "--no-audio", "-m", "720", "--max-fps=15", "-b", "2M",
                     "--window-title", "yuMAArin 监工", "--window-width=360"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env)
                self._scrcpy_lbl.set_text("不监工了")
                self.logln(f"已打开 scrcpy 监工（{addr}）；关掉窗口不影响任务")
            except Exception as e:
                self.logln(f"[scrcpy 启动失败] {e}"); btn.set_active(False)
        else:
            self._kill_proc(getattr(self, "_scrcpy_proc", None)); self._scrcpy_proc = None
            self._scrcpy_lbl.set_text("监工(scrcpy)")

    def _open_waydroid(self):
        # waydroid show-full-ui 只是通知会话显示、命令随即退出；窗口由会话进程绘制，
        # 无法用命令行隐藏（只能在窗口自己的 × 关闭）。故这里只做「显示」。
        import shutil
        exe = shutil.which("waydroid") or "/usr/bin/waydroid"
        try:
            subprocess.Popen([exe, "show-full-ui"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            self.logln("已请求显示 Waydroid 窗口；关闭请点窗口自己的 ×（不影响任务）")
        except Exception as e:
            self.logln(f"[Waydroid 启动失败] {e}")

    def _sync_view_buttons(self):
        # 同步 scrcpy 开关状态（窗口被外部关掉时复位按钮）
        if getattr(self, "_scrcpy_proc", None) and self._scrcpy_proc.poll() is not None:
            self._scrcpy_proc = None; self.tg_scrcpy.set_active(False)
        return True

    def on_run_selected(self, _b):
        self.write_and_run(self.modules)

    def on_preset_daily(self, _b):
        for m in list(self.modules): self.mod_list.remove(m["row"])
        self.modules = []
        for t in ("StartUp","Fight","Recruit","Infrast","Mall","Award"):
            self.add_module(t)
        fights = [m for m in self.modules if m["spec"]["type"] == "Fight"]
        if fights:
            self.set_param(fights[0], "stage", "Annihilation")
            self.set_param(fights[0], "times_enabled", True); self.set_param(fights[0], "times", 1)
        if self.modules: self.mod_list.select_row(self.modules[0]["row"])
        self.logln("已套用一键日常模块（开始唤醒/理智作战/公开招募/基建换班/信用收支/领取奖励）")

    # ---------- 自动战斗页 ----------
    def page_copilot(self):
        # field: (参数名, 标签, kind, 默认, choices, 是否位置, 多值)  kind: str/enum/flag
        COMBAT = [
            ("copilot", "普通作业（自动抄作业）", [
                ("URI_LIST","作业 URI/路径（可批量添加，按序连续运行）","slist",[],None,True,True),
                ("--raid","突袭","enum","normal",[("normal","普通"),("raid","突袭"),("both","两者")],False,False),
                ("--formation","自动编队(多关卡时强制)","flag",False,None,False,False),
                ("--formation-index","编队序号","str","",None,False,False),
                ("--add-trust","自动补信赖","flag",False,None,False,False),
                ("--ignore-requirements","忽略干员需求","flag",False,None,False,False),
                ("--use-sanity-potion","使用理智药","flag",False,None,False,False),
                ("--support-unit-usage","助战用法","enum","",[("","(默认)"),("0","不助战"),("1","仅缺1干员时"),("2","缺1时用指定干员"),("3","缺1时用随机干员")],False,False),
                ("--support-unit-name","助战干员名","str","",None,False,False),
                ("--loop-times","循环次数","str","1",None,False,False)]),
            ("ssscopilot", "保全派驻", [
                ("URI","作业 URI/路径","str","",None,True,False),
                ("--loop-times","循环次数","str","1",None,False,False)]),
            ("paradoxcopilot", "悖论模拟", [
                ("URI_LIST","作业 URI/路径(多个空格分隔)","str","",None,True,True)]),
        ]
        # 对齐官方 CopilotView：左侧子页导航（ListBox）+ 右侧表单 + 底部居中「开始/停止」
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top","bottom","start","end"): getattr(box, f"set_margin_{m}")(8)
        # 官方 CopilotView 的 3 个链接（文案照官方）：自动战斗作业分享 / 视频链接 / 自动战斗地图坐标
        links = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for lab, uri in (("自动战斗作业分享", "https://prts.plus"),
                         ("视频链接", "https://www.bilibili.com/video/"),
                         ("自动战斗地图坐标", "https://map.ark-nights.com/areas?coord_override=maa")):
            links.append(Gtk.LinkButton.new_with_label(uri, lab))
        box.append(links)
        hp = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL); hp.set_vexpand(True); hp.set_position(160)
        hp.set_shrink_start_child(False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.set_size_request(160, -1); left.add_css_class("task-column")
        for m in ("top","bottom","start","end"): getattr(left, f"set_margin_{m}")(4)
        nav = Gtk.ListBox(); nav.set_selection_mode(Gtk.SelectionMode.SINGLE); nav.set_size_request(148, -1)
        left.append(nav); hp.set_start_child(left)

        stack = Gtk.Stack(); stack.set_vexpand(True)
        right_scroll = Gtk.ScrolledWindow(); right_scroll.set_vexpand(True)
        right_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        right_scroll.set_child(stack); hp.set_end_child(right_scroll)
        box.append(hp)

        self.combat_forms = {}
        for cmd, label, fields in COMBAT:
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            for m in ("top","bottom","start","end"): getattr(inner, f"set_margin_{m}")(8)
            wids = []
            for (name, lab, kind, dflt, choices, pos, multi) in fields:
                r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                l = Gtk.Label(label=lab); l.set_xalign(0); l.set_size_request(230, -1); r.append(l)
                if kind == "flag":
                    w = Gtk.CheckButton(); w.set_active(bool(dflt))
                elif kind == "enum":
                    w = make_widget("enum", dflt, choices)
                elif kind == "slist":
                    w = make_widget("slist", dflt, None, {"placeholder": "作业 URI/路径（可填多个）"}); w.set_hexpand(True)
                else:
                    w = make_widget("str", dflt, None)
                r.append(w); inner.append(r); wids.append((name, kind, w, pos, multi))
            stack.add_named(inner, cmd)
            nrow = Gtk.ListBoxRow(); nlab = Gtk.Label(label=label); nlab.set_xalign(0); nrow.set_child(nlab)
            nrow._cmd = cmd; nav.append(nrow)
            self.combat_forms[cmd] = wids
        def on_nav(_lb, r):
            if r: stack.set_visible_child_name(r._cmd)
        nav.connect("row-selected", on_nav)
        nav.select_row(nav.get_row_at_index(0))
        bb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10); bb.set_halign(Gtk.Align.CENTER)
        for lab, fn, cls in [("开始", lambda _b: self.on_run_active_combat(stack), "suggested-action"),
                             ("停止", self.on_stop, None)]:
            b = Gtk.Button(label=lab); b.set_size_request(110, 46)
            if cls: b.add_css_class(cls)
            b.connect("clicked", fn); bb.append(b)
        box.append(bb)
        return box

    def on_run_active_combat(self, stack):
        cmd = stack.get_visible_child_name()
        wids = self.combat_forms.get(cmd)
        if cmd and wids is not None: self.on_run_combat(cmd, wids)

    def on_run_combat(self, cmd, wids):
        argv = [cmd]
        for name, kind, w, pos, multi in wids:
            if kind == "flag":
                if w.get_active(): argv.append(name)
                continue
            if kind == "slist":
                argv += [u for u in (widget_value(w) or []) if u]   # 批量作业：按序多个 URI
                continue
            v = widget_value(w)
            if v == "": continue
            if pos:
                argv += v.split() if multi else [v]
            else:
                argv += [name, v]
        self._maybe_show_game_window()
        self.run_maa(argv)

    # ---------- 设置页 ----------
    def _install_css(self):
        # 对齐官方 Res/Styles/*：按钮高度 30 / 圆角 4；ListBox 项 hover/选中用叠加底色；
        # 分区用「1px 边框 + 去上边 + 底部圆角」包住（BorderThickness=1,0,1,1 / CornerRadius=0,0,4,4）。
        if getattr(self, "_css_done", False): return
        css = b"""
        .settings-section {
          border: 1px solid alpha(@theme_fg_color, 0.16);
          border-top-width: 0;
          border-radius: 0 0 6px 6px;
          padding: 10px 12px;
        }
        .setting-label { opacity: 0.92; }
        expander > title { padding: 5px 2px; }
        .settings-about label { opacity: 0.9; }
        button { min-height: 30px; border-radius: 4px; }
        button.action { min-height: 22px; min-width: 22px; padding: 0 4px; }
        listbox { background-color: alpha(@theme_fg_color, 0.035); border-radius: 4px; }
        listbox > row { border-radius: 4px; padding: 3px 8px; }
        listbox > row:hover { background-color: alpha(@theme_fg_color, 0.07); }
        listbox > row:selected { background-color: alpha(@theme_fg_color, 0.12); }
        entry, searchentry { border-radius: 4px; min-height: 30px; }
        .progress-icon { font-feature-settings: "tnum"; }
        .task-column {
          background-color: alpha(@theme_fg_color, 0.035);
          border: 1px solid alpha(@theme_fg_color, 0.16);
          border-radius: 4px;
        }
        .task-row { border-radius: 4px; }
        .task-row.inprogress { background-color: alpha(#326cf3, 0.16); }
        .task-row.completed  { background-color: alpha(#90ee90, 0.18); }
        .task-row.error      { background-color: alpha(#ff4444, 0.16); }
        .task-row.skipped    { opacity: 0.5; }
        .task-gear { min-height: 22px; min-width: 22px; padding: 0 4px; }
        .info-dot { opacity: 0.5; }
        .log-line { font-family: monospace; font-size: 85%; }
        .form-group {
          font-weight: bold;
          margin-top: 8px;
          padding: 2px 0 3px 0;
          border-bottom: 1px solid alpha(@theme_fg_color, 0.12);
        }
        """
        prov = Gtk.CssProvider(); prov.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css_done = True

    def apply_theme(self, mode):
        s = Gtk.Settings.get_default()
        if not s: return
        if mode == "system":
            # 跟随 GNOME 系统深浅色（读 org.gnome.desktop.interface color-scheme，并监听其变化）
            try:
                gs = getattr(self, "_theme_gs", None) or Gio.Settings.new("org.gnome.desktop.interface")
                self._theme_gs = gs
                if not getattr(self, "_theme_watch", False):
                    gs.connect("changed::color-scheme", lambda *_: self.apply_theme("system"))
                    self._theme_watch = True
                s.set_property("gtk-application-prefer-dark-theme",
                               gs.get_string("color-scheme") == "prefer-dark")
                return
            except Exception:
                pass
        s.set_property("gtk-application-prefer-dark-theme", mode == "dark")

    def set_autostart_file(self, enabled):
        # 对齐官方「开机自启」：管理 ~/.config/autostart/yumaarin.desktop
        path = os.path.expanduser("~/.config/autostart/yumaarin.desktop")
        if enabled:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            home = os.path.expanduser("~")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\nName=yuMAArin\n"
                        "Comment=明日方舟日常（maa-cli 前端，开机自启）\n"
                        f"Exec={home}/.local/bin/yumaarin-autostart.sh\n"
                        f"Icon={home}/.local/share/icons/yumaarin.png\n"
                        "Terminal=false\nX-GNOME-Autostart-enabled=true\n")
        else:
            try: os.remove(path)
            except FileNotFoundError: pass

    def _settings_row(self, key, label, kind, dflt, choices, extra=None):
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        l = Gtk.Label(label=label); l.set_xalign(0); l.set_size_request(190, -1); l.add_css_class("setting-label")
        r.append(l)
        w = make_widget(kind, dflt, choices, extra)
        if kind in ("kv", "rows", "slist", "text"): w.set_hexpand(True)
        r.append(w); self.set_wids[key] = w
        return r

    def page_settings(self):
        # 对齐官方 SettingsView：左「搜索 + 分区列表」，右「可折叠 Expander 分区（带边框圆角）」。
        self._install_css()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top","bottom","start","end"): getattr(outer, f"set_margin_{m}")(8)
        try: prof = json.load(open(PROFILE))
        except Exception: prof = {}
        st = load_state(); game = st.get("game", {})
        conn = prof.get("connection", {}); inst = prof.get("instance_options", {})
        static = prof.get("static_options", {})
        autostart_on = os.path.exists(os.path.expanduser("~/.config/autostart/yumaarin.desktop"))
        self.set_wids = {}

        hp = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL); hp.set_vexpand(True); hp.set_position(190)
        hp.set_shrink_start_child(False)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); left.set_size_request(175, -1)
        self.set_search = Gtk.SearchEntry(); self.set_search.set_placeholder_text("搜索设置")
        self.set_list = Gtk.ListBox(); self.set_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        lscroll = Gtk.ScrolledWindow(); lscroll.set_vexpand(True); lscroll.set_child(self.set_list)
        left.append(self.set_search); left.append(lscroll)
        hp.set_start_child(left)

        self.set_scroll = Gtk.ScrolledWindow(); self.set_scroll.set_vexpand(True)
        self.set_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_secbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("top","bottom","start","end"): getattr(self.set_secbox, f"set_margin_{m}")(6)
        self.set_scroll.set_child(self.set_secbox)
        hp.set_end_child(self.set_scroll)
        outer.append(hp)

        self._sec_items = []

        def add_section(title, rows, about=False):
            exp = Gtk.Expander(label=title); exp.set_expanded(True)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            content.add_css_class("settings-section")
            labels = [title]
            if about:
                content.add_css_class("settings-about")
                for t in ("yuMAArin — 一键长草", "后端：maa-cli / MaaCore",
                          f"profile：{PROFILE}", "对齐官方 MaaWpfGui（dev-v2）布局与参数"):
                    L = Gtk.Label(label=t); L.set_xalign(0); content.append(L)
            for row in rows:
                if row is None:
                    content.append(Gtk.Separator()); continue
                key, label, kind, dflt, choices = row[:5]
                extra = row[5] if len(row) > 5 else None
                content.append(self._settings_row(key, label, kind, dflt, choices, extra))
                labels.append(label)
            exp.set_child(content)
            self.set_secbox.append(exp)
            lrow = Gtk.ListBoxRow(); llab = Gtk.Label(label=title); llab.set_xalign(0); lrow.set_child(llab)
            self.set_list.append(lrow)
            self._sec_items.append({"title": title, "row": lrow, "exp": exp, "text": " ".join(labels).lower()})
            return exp

        # —— 分区（顺序/名称照官方 SettingsView；字段照各 Settings/*.xaml，仅保留能落到 maa-cli/profile/state 的项）——
        add_section("性能", [
            ("gpu_ocr","GPU 推理设备(空=CPU)","str",str(static.get("gpu_ocr","")),None),
            ("cpu_ocr","使用 CPU OCR","bool",static.get("cpu_ocr",True),None),
        ])
        add_section("游戏", [
            ("client_type","客户端","enum",game.get("client_type","Official"),CLIENTS),
            ("deployment_with_pause","部署时暂停","bool",inst.get("deployment_with_pause",False),None),
        ])
        add_section("连接", [
            ("adb_path","ADB 路径","str",conn.get("adb_path", os.path.expanduser("~/.local/bin/adb")),None),
            ("address","连接地址","str",conn.get("address", DEFAULT_ADDR),None),
            ("config","连接配置","str",conn.get("config","Waydroid"),None),
            ("touch_mode","触控模式","enum",inst.get("touch_mode","MaaTouch"),
             [("MiniTouch","Minitouch（默认）"),("MaaTouch","MaaTouch（实验功能）"),("ADB","ADB Input（不推荐使用）"),("MaaFwAdb","MaaFwAdb（实验功能）")]),
            ("adb_lite_enabled","ADB Lite","bool",inst.get("adb_lite_enabled",False),None),
            ("kill_adb_on_exit","退出时结束 ADB","bool",inst.get("kill_adb_on_exit",False),None),
            ("retry_on_disconnected","断连时重试","bool",st.get("retry_on_disconnected",False),None),
            ("allow_adb_restart","允许重启 ADB","bool",st.get("allow_adb_restart",False),None),
        ])
        add_section("启动", [
            ("autostart","开机自启","bool",autostart_on,None),
            ("run_daily_on_launch","启动后自动运行日常","bool",st.get("run_daily_on_launch",False),None),
        ])
        add_section("界面", [
            ("theme","主题","enum",st.get("theme","system"),
             [("light","亮色"),("dark","暗色"),("system","与系统同步")]),
            ("notify_on_finish","任务结束时系统通知","bool",st.get("notify_on_finish",False),None),
            ("recall_size","记住窗口尺寸","bool",st.get("recall_size",True),None),
        ])
        add_section("三方服务", [
            ("report_to_penguin","上报企鹅物流","bool",game.get("report_to_penguin",False),None),
            ("penguin_id","企鹅 ID","str",game.get("penguin_id",""),None),
            ("report_to_yituliu","上报一图流","bool",game.get("report_to_yituliu",False),None),
            ("yituliu_id","一图流 ID","str",game.get("yituliu_id",""),None),
        ])
        add_section("定时", [
            ("timer_enabled","启用定时执行","bool",st.get("timer_enabled",False),None),
            ("timer_time","执行时间(HH:MM)","str",st.get("timer_time","04:00"),None),
        ])
        add_section("外部通知", [
            ("webhook_enabled","启用自定义 Webhook","bool",st.get("webhook_enabled",False),None),
            ("webhook_url","Webhook URL","str",st.get("webhook_url",""),None),
            ("webhook_headers","Headers(每行 名称: 值)","text",
             st.get("webhook_headers","Content-Type: application/json; charset=utf-8"),None),
            ("webhook_body","消息体模板({title}/{content}/{time})","text",
             st.get("webhook_body",'{"title":"{title}","content":"{content}","time":"{time}"}'),None),
            ("webhook_when","发送时机","enum",st.get("webhook_when","complete"),
             [("complete","完成时"),("error","出错时"),("both","两者")]),
        ])
        add_section("更新", [
            ("check_update_on_start","启动时检查更新","bool",st.get("check_update_on_start",True),None),
            ("channel","更新通道","enum",st.get("update_channel","stable"),
             [("stable","正式版"),("beta","公测版"),("nightly","内测版")]),
            ("proxy","更新代理(空=自动探测)","str",st.get("proxy",""),None),
        ])
        exp = add_section("维护", [])
        mc = exp.get_child()
        for lab, args in (("更新核心 / 资源", ["update"]), ("热更新资源", ["hot-update"]), ("清理缓存", ["cleanup"])):
            b = Gtk.Button(label=lab); b.set_halign(Gtk.Align.START)
            b.connect("clicked", lambda _b, a=args: self.run_maa(a)); mc.append(b)
        note = Gtk.Label(label=(
            "说明：官方「小工具」页的识别功能（仓库识别 / 干员识别 / 公招识别 / 视频识别 / "
            "抽卡 / 偷看 / 小游戏）由 MaaWpfGui 直接调用 MaaCore API 实现；本前端基于 maa-cli，"
            "没有对应的识别命令，故不提供该页。需要这些功能请用官方 MAA。"))
        note.set_xalign(0); note.set_wrap(True); note.add_css_class("dim-label"); mc.append(note)
        add_section("关于", [], about=True)

        def on_search(_e):
            q = self.set_search.get_text().strip().lower()
            for it in self._sec_items:
                vis = (q == "" or q in it["text"])
                it["row"].set_visible(vis); it["exp"].set_visible(vis)
        self.set_search.connect("search-changed", on_search)

        def on_sel(_lb, r):
            if not r: return
            for it in self._sec_items:
                if it["row"] is r:
                    it["exp"].set_expanded(True); it["exp"].grab_focus(); break
        self.set_list.connect("row-selected", on_sel)
        self.set_list.select_row(self.set_list.get_row_at_index(0))

        save = Gtk.Button(label="保存设置"); save.add_css_class("suggested-action")
        save.set_halign(Gtk.Align.END)
        save.connect("clicked", self.on_save_settings)
        outer.append(save)
        return outer

    def on_save_settings(self, _b):
        v = lambda k: widget_value(self.set_wids[k])
        prof = {"connection": {"adb_path": v("adb_path"), "address": v("address"), "config": v("config")},
                "instance_options": {"touch_mode": v("touch_mode"), "deployment_with_pause": bool(v("deployment_with_pause")),
                                     "adb_lite_enabled": bool(v("adb_lite_enabled")),
                                     "kill_adb_on_exit": bool(v("kill_adb_on_exit"))},
                "static_options": {"cpu_ocr": bool(v("cpu_ocr"))}}
        g = str(v("gpu_ocr"))
        if g.strip() != "":
            try: prof["static_options"]["gpu_ocr"] = int(g)
            except Exception: pass
        os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
        with open(PROFILE, "w", encoding="utf-8") as f: json.dump(prof, f, ensure_ascii=False, indent=2)
        st = load_state()
        st["game"] = {"client_type": v("client_type"), "report_to_penguin": v("report_to_penguin"),
                      "penguin_id": v("penguin_id"), "report_to_yituliu": v("report_to_yituliu"),
                      "yituliu_id": v("yituliu_id")}
        st["update_channel"] = v("channel")
        st["theme"] = v("theme")
        st["check_update_on_start"] = bool(v("check_update_on_start"))
        st["recall_size"] = bool(v("recall_size"))
        st["run_daily_on_launch"] = bool(v("run_daily_on_launch"))
        st["notify_on_finish"] = bool(v("notify_on_finish"))
        st["timer_enabled"] = bool(v("timer_enabled"))
        st["timer_time"] = str(v("timer_time"))
        st["retry_on_disconnected"] = bool(v("retry_on_disconnected"))
        st["allow_adb_restart"] = bool(v("allow_adb_restart"))
        st["proxy"] = str(v("proxy"))
        st["webhook_enabled"] = bool(v("webhook_enabled"))
        st["webhook_url"] = str(v("webhook_url"))
        st["webhook_headers"] = str(v("webhook_headers"))
        st["webhook_body"] = str(v("webhook_body"))
        st["webhook_when"] = str(v("webhook_when"))
        save_state(st)
        self.set_autostart_file(bool(v("autostart")))
        self.apply_theme(v("theme"))
        if hasattr(self, "addr_label"): self.addr_label.set_text(str(v("address")))
        self.logln(f"已保存设置：profile + state（{PROFILE}）")

    # ---------- 工具页 ----------
    def page_tools(self):
        # 对齐官方 ToolboxView：用分页(TabControl)组织功能
        GROUPS = [("查询", ["version","activity","remainder","dir","list"]),
                  ("维护", ["update","hot-update","cleanup"])]
        toold = {c: (label, fields) for c, label, fields in TOOLS}
        nbi = Gtk.Notebook(); nbi.set_vexpand(True)
        for gname, cmds in GROUPS:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for m in ("top","bottom","start","end"): getattr(box, f"set_margin_{m}")(8)
            for c in cmds:
                if c not in toold: continue
                label, fields = toold[c]
                fr = Gtk.Frame(label=f"{label}（{c}）")
                inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                for m in ("top","bottom","start","end"): getattr(inner, f"set_margin_{m}")(6)
                wids = []
                for (name, flabel, dflt, pos, choices) in fields:
                    inner.append(Gtk.Label(label=flabel))
                    w = make_widget("enum" if choices else "str", dflt, choices); inner.append(w)
                    wids.append((name, pos, w))
                run = Gtk.Button(label="执行")
                run.connect("clicked", lambda _b, cc=c, ws=wids: self.on_run_tool(cc, ws))
                inner.append(run); fr.set_child(inner); box.append(fr)
            nbi.append_page(self._scroll(box), Gtk.Label(label=gname))
        return nbi

    def on_run_tool(self, cmd, wids):
        argv = [cmd]
        for name, pos, w in wids:
            v = widget_value(w)
            if pos:
                if v == "": continue
                argv += v.split()
            else:
                if v == "": continue
                argv += [name, v]
        self.run_maa(argv)

if __name__ == "__main__":
    App().run()
