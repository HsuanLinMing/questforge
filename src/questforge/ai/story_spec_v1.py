# src/questforge/ai/story_spec_v1.py
from __future__ import annotations

import hashlib
import json
import re
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from questforge.ai.story_prompt_assets import (
    STORY_PROMPT_V1_MD,
    SCHEMA_STORY_NODES_MD,
    GUARD_RULES_MD,
    STORY_RESPONSE_WHITELIST_MD,
    WORLD_OLD_RIVAL_MODULE_MD,
)
from questforge.ai.story_style_examples import extract_style_example as extract_sample_style_example

JsonDict = Dict[str, Any]

# -------------------------
# Few-shot: 黃金開場（節奏錨點）
# -------------------------
GOLDEN_OPENING_EXAMPLE = """
【黃金開場示範（僅示範節奏，禁止照抄內容）】
旁白：廣播阿姨阿秀一手按著快滑下來的耳機，一手朝舞台那頭揮，像恨不得自己多長兩隻手。

旁白：今天是學校的才藝園遊會，舞台那邊在試音，攤位那邊在貼價目表，報到桌前面一排人拿著表演單、名牌和膠帶，誰都說自己只差最後一下。

霏霏：每次有人說「只差最後一下」，通常後面都還有十下。

樂樂：那我今天很厲害，我只差吃一口。

霏霏：你嘴巴那個已經不是一口，是半根熱狗了。

旁白：樂樂把熱狗往後藏，藏得像全世界只要看不到，他就不算偷吃。

樂樂：我這叫先幫忙試溫度。

霏霏：喔，原來你是熱狗檢查員。

旁白：舞台前面的主持人白鷺阿冠拿著麥克風，一下試高音，一下試低音，試到旁邊幫忙拉線的同學都開始翻白眼。

白鷺阿冠：各位來賓！各位同學！等一下我的開場，如果你們沒有被震住，表示音響還不夠大！

樂樂：他講得好像等一下要從舞台上發射出去。

霏霏：放心，他先發射的應該是口水。

旁白：報到桌前，鉛筆小白抱著一疊號碼牌，嘴上一直說不急不急，腳步卻快得像在跟時間打架。

鉛筆小白：三年二班先來領表演牌！拿到的人不要亂放，真的不要亂放，我今天已經說第八次了！

樂樂：她嘴巴說不急，聲音像快要起飛。

霏霏：那是因為今天每個人都在硬撐自己很穩。

旁白：後台道具區更忙，有人扶著紙板城堡，有人追著一直滾走的呼拉圈，還有人抱著點心箱在隊伍中間鑽來鑽去。

滷寶：借過借過，誰訂的紅豆餅先來拿，不然等一下冷掉我不負責喔！

樂樂：我可以先幫大家保管一個。

霏霏：你那不叫保管，叫消失。

旁白：旁邊的工作人員剛把抽獎箱搬到服務台，另一頭又有人叫他去幫忙掛海報，整個場子像每一個角落都在同時喊「先來這邊」。

廣播阿姨阿秀：請表演隊伍注意，第一輪彩排五分鐘後開始。還沒報到的班級，不要再派一個人慢慢走過來了。

樂樂：廣播姊姊是不是已經生氣了？

霏霏：不是生氣，是忙到笑不出來。

旁白：霏霏一手把樂樂往報到桌那邊推，一手順便接住差點從椅背滑下來的亮片外套。

霏霏：先把人帶好、把東西放好、把嘴巴擦好。今天我們至少要做到其中兩個。

樂樂：我覺得第三個最難，因為熱狗很努力。

旁白：前面有人在練舞，後面有人在找插座，服務台在對名單，舞台在試燈，連風一吹過去，都像忙著把彩帶吹去下一站。

旁白：整個活動還沒正式開始，可是每個人已經像站在快要往前衝的起跑線上，只等誰先喊一聲「好了沒有」。
""".strip()


def extract_style_example(max_lines: int = 72, *, selector: str = "", focus: str = "general") -> str:
    """抽取樣本故事前段作為節奏示範（只學節奏/口吻，不可照抄內容）"""
    return extract_sample_style_example(max_lines=max_lines, selector=selector, focus=focus)


@dataclass
class StorySpecV1:
    """
    ✅ 原則：以「規範引導 AI 自行生成」為主。
    - spec 只負責：規範、gate、報告、repair/enrich 的指令。
    - 不在 spec 裡「寫死劇情」或做大量替換改寫。

    ✅ 本版關鍵修正：
    - 「事件」判定不靠關鍵字；必須存在 scene_02_incident 節點，並維持在開場 warmup 之後自然爆出。
    - 不允許「幫小朋友整理線索/重點回顧/替讀者排除」的教學式總結（孩子要自己判斷與記住）。
      允許偶爾出現很離譜的假線索被吐槽，但不應每次都強制排除/整理。
    """

    prompts_dir: Path = Path("src/questforge/ai/prompts")  # kept for backwards compatibility
    core_files: List[str] = None  # set in __post_init__

    unsure_choice_text: str = "我還不確定，交給大人"

    # 開場段落數（以 \n\n 分段）
    opening_min_paragraphs: int = 14
    pre_incident_min_paragraphs: int = 30

    # 事件節點 id（用來判定「有事件」）
    incident_node_id: str = "scene_02_incident"

    # 結尾完整性
    ending_min_paragraphs: int = 6

    # 生成完成後，額外做一次語句自然度潤句
    enable_post_polish: bool = True

    # 事件後至少要有幾個自然搜尋 scene（避免事件一出就指認）
    min_scene_nodes_after_required: int = 2

    # 開場禁詞（scene_01_start 全禁：包含引號/轉述/台詞）
    incident_terms_for_opening_ban: List[str] = None
    forbidden_opening_terms: List[str] = None

    # 禁止 placeholder 命名
    banned_placeholders: List[str] = None
    placeholder_role_regex_patterns: List[str] = None

    # 禁止泛稱（要求配角要有名字）
    banned_generics: List[str] = None
    generic_side_speaker_labels: List[str] = None

    # 禁止遊戲提示口吻（不要對讀者下指令）
    gamey_patterns: List[str] = None

    # ✅ 禁止「替讀者整理/記重點/總結線索」口吻（全篇禁止）
    # （注意：不是禁止角色聊天說「我整理一下」，而是禁止出現「幫你整理重點/你要記住...」這種教學指令式總結）
    banned_reader_hint_patterns: List[str] = None

    # ✅ 禁止空泛 AI 說書腔 / 套句
    banned_generic_prose_patterns: List[str] = None
    generic_prose_regex_patterns: List[str] = None
    opening_overview_regex_patterns: List[str] = None
    ending_moralizing_patterns: List[str] = None
    ending_moralizing_regex_patterns: List[str] = None
    arrival_context_markers: List[str] = None
    arrival_context_regex_patterns: List[str] = None
    admission_markers: List[str] = None
    admission_action_markers: List[str] = None
    relationship_grounding_markers: List[str] = None
    bigger_consequence_markers: List[str] = None
    adult_takeover_markers: List[str] = None

    # ✅ final_accuse 禁止逼問 / 審訊語氣
    banned_accuse_tone_patterns: List[str] = None

    # ✅ 事件不能在剛發生就自己收掉
    incident_flat_resolution_patterns: List[str] = None

    # ✅ 開場「安全句型示範」（repair 用）
    opening_safe_patterns: List[str] = None

    # cases 殘影（避免帶到別案名詞）
    banned_proper_nouns: List[str] = None

    allowed_background_themes: Optional[List[str]] = None
    theme_grounding_hints: Optional[Dict[str, str]] = None
    story_engine_cards: Optional[List[Dict[str, Any]]] = None
    incident_shape_cards: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self) -> None:
        if self.core_files is None:
            self.core_files = [
                "schema_story_nodes.md",
                "guard_rules.md",
                "story_response_whitelist.md",
                "world_old_rival_module.md",
            ]

        if self.allowed_background_themes is None:
            self.allowed_background_themes = [
                "校園園遊會準備時段",
                "校園才藝日的後台到舞台區",
                "社區慶典主舞台與攤位區",
                "百貨公司大型活動樓層",
                "運動中心親子挑戰賽",
                "港口首航發表日",
                "海邊活動日與救生站周邊",
                "遊樂園節慶活動日",
                "車站集章旅行活動日",
                "校外教學闖關日",
                "夜市活動日",
                "美食比賽或評選日",
                "山林步道健行活動日",
                "溫泉飯店活動日",
                "度假村大廳到泳池區",
                "渡假山莊晚會準備時段",
            ]

        if self.theme_grounding_hints is None:
            self.theme_grounding_hints = {
                "校園園遊會準備時段": "操場、班級攤位、報到桌、抽獎區、廣播、表演隊伍、老師與家長都在流動。",
                "校園才藝日的後台到舞台區": "舞台、後台道具區、候場隊伍、報到桌、試音、主持人、工作同學一起忙。",
                "社區慶典主舞台與攤位區": "主舞台、攤位、服務台、來賓、工作人員、抽獎或表演流程同時在跑。",
                "百貨公司大型活動樓層": "樓層櫃位、服務台、活動舞台、試吃區、排隊人潮、廣播和電梯動線都要像百貨。",
                "運動中心親子挑戰賽": "跑道、計分桌、關卡區、觀眾席、裁判、報到處、水站和隊伍在運作。",
                "港口首航發表日": "碼頭、來賓區、媒體、工作人員、船邊動線、登船名單、主持與發表流程都是真的。",
                "海邊活動日與救生站周邊": "沙灘活動、救生站、寄物處、補水區、廣播、遊客與工作人員一起流動。",
                "遊樂園節慶活動日": "入口、排隊動線、表演區、工作人員、遊客、活動章或紀念品都要像遊樂園，不是 generic 園遊會。",
                "車站集章旅行活動日": "月台、服務台、時刻表、旅客、站務員、列車廣播、集章冊和候車人潮都要像車站。",
                "校外教學闖關日": "集合點、老師帶隊、關卡、地圖、隊伍移動、工作人員與同學同時在跑。",
                "夜市活動日": "攤位、叫賣聲、排隊、走道、遊戲攤、工作人員、垃圾桶和香味都要像夜市。",
                "美食比賽或評選日": "評審席、試吃桌、主持人、參賽隊伍、後場備料、工作人員和觀眾同時在場。",
                "山林步道健行活動日": "登山口、步道、補給站、領隊、遊客中心、地圖牌、休息亭和隊伍節奏都要像真的健行日。",
                "溫泉飯店活動日": "大廳、櫃台、行李車、活動看板、餐廳、溫泉區入口、服務人員與住客動線都要像飯店。",
                "度假村大廳到泳池區": "報到大廳、泳池邊、活動舞台、房卡、接駁車、服務人員與遊客行程都要像度假村。",
                "渡假山莊晚會準備時段": "山莊大廳、木棧道、晚會場地、點燈區、餐廳、工作人員與旅客的準備節奏都要像度假山莊。",
            }

        if self.story_engine_cards is None:
            self.story_engine_cards = [
                {
                    "name": "面子撐場型",
                    "setup": "一個很想把場面撐得漂亮的人，表面很穩，實際上已經快要兜不住。",
                    "pressure": "這件事會影響上台順序、公開表現、來賓觀感，或讓某個人當場很難堪。",
                    "mislead": "先讓大家以為是某個愛現的人搞砸，再慢慢發現他其實在遮另一件丟臉的事。",
                    "human_core": "真相和逞強、怕丟臉、想保住面子有關。",
                },
                {
                    "name": "好心弄歪型",
                    "setup": "有人原本想幫忙、想補救、想偷偷做好事，結果越幫越亂。",
                    "pressure": "麻煩不是小事，會卡住流程、延後活動、或害別人以為被針對。",
                    "mislead": "先看起來像是惡意，後來才發現是好心做錯，再往下翻出他為什麼不敢說。",
                    "human_core": "真相和嘴硬、怕被笑、怕承認失手有關。",
                },
                {
                    "name": "說半套型",
                    "setup": "至少一個人從頭到尾沒有全說實話，但不是單純說謊，而是故意漏掉最難開口的部分。",
                    "pressure": "大家一開始會因為這個半真半假的說法，把矛頭指錯地方。",
                    "mislead": "第一個可疑的人很像有鬼，第二個人的說法又把事情扭掉，最後才拼成完整畫面。",
                    "human_core": "真相和難為情、怕被罵、怕連累別人有關。",
                },
                {
                    "name": "流程卡住型",
                    "setup": "活動照理應該順順往前走，結果某個關鍵安排突然卡住。",
                    "pressure": "如果不弄清楚，整場活動的順序、評分、上台或闖關都會被拖住。",
                    "mislead": "表面像是單純東西沒到位，實際上是時間、位置、誰碰過什麼對不上。",
                    "human_core": "真相和慌張補位、臨時改動、有人不敢承認自己手忙腳亂有關。",
                },
                {
                    "name": "傳話走樣型",
                    "setup": "現場的耳語、抱怨、插話越傳越歪，讓某個人看起來超可疑。",
                    "pressure": "不只是誤會，還會讓那個人當場被大家盯著看，甚至影響他要做的事。",
                    "mislead": "先讓傳聞聽起來很像真的，再用現場細節慢慢把它戳破。",
                    "human_core": "真相和愛八卦、想搶話、怕自己搞錯卻硬撐有關。",
                },
                {
                    "name": "兩層誤會型",
                    "setup": "事件表面有一層很明顯的誤會，底下還藏著另一層更難堪的原因。",
                    "pressure": "外層誤會先讓大家亂成一團，內層原因才是角色死不肯講的關鍵。",
                    "mislead": "讓第一個答案看起來很順，再翻掉；第二個答案也能講通一半，最後才對上。",
                    "human_core": "真相和嫉妒、逞強、想被看見、想搶回注意力有關。",
                },
                {
                    "name": "假熟練型",
                    "setup": "一個看起來最熟、最懂、最像主力的人，反而因為太想裝熟把事情越搞越怪。",
                    "pressure": "大家原本都倚賴他，所以他一出錯，現場氣氛會先僵掉。",
                    "mislead": "先讓人以為他一定沒問題，再從小破口看出他其實一直在硬撐。",
                    "human_core": "真相和愛現、怕掉面子、怕承認自己其實沒那麼會有關。",
                },
                {
                    "name": "保護別人型",
                    "setup": "有人一直幫另一個人遮，導致整件事越看越像另有鬼。",
                    "pressure": "遮掩行為會讓大家誤會對象，還可能拖累活動正常進行。",
                    "mislead": "先讓保護者看起來像兇手，再慢慢看出他是在替別人的難堪擋風頭。",
                    "human_core": "真相和護短、義氣、怕朋友出糗有關。",
                },
                {
                    "name": "搶風頭搞事型",
                    "setup": "有人不甘心自己被比下去，乾脆偷偷動手腳，想讓別人的風頭先垮掉。",
                    "pressure": "一旦成功，不只是某個人難堪，還會把整場活動順序、表現或觀感一起帶歪。",
                    "mislead": "先讓大家以為只是現場太亂，再慢慢看出有人其實故意換掉、藏起來或亂改過。",
                    "human_core": "真相和想搶注意力、怕輸、氣不過別人太受歡迎有關。",
                },
                {
                    "name": "嫉妒動手型",
                    "setup": "有人看別人太出風頭，嘴上裝沒事，私下卻偷偷搞了一點小破壞。",
                    "pressure": "那個小動作會直接害人出糗、延誤、錯失機會，現場氣氛也會立刻偏向錯的人。",
                    "mislead": "先讓嫌疑落在最表面的倒楣鬼身上，後來才看到真正動手的人其實早就不爽很久。",
                    "human_core": "真相和嫉妒、想報復、想讓別人也嚐嚐難堪有關。",
                },
                {
                    "name": "假幫忙真搞鬼型",
                    "setup": "有人表面說要幫忙，實際上卻趁機偷換、亂放、偷改，讓自己或朋友佔到便宜。",
                    "pressure": "因為他打著幫忙的名義，大家一開始更難懷疑他，場面也更容易拖住。",
                    "mislead": "先讓這個人看起來只是跑很快、很熱心，再慢慢發現他其實每次靠近關鍵物件都在動手腳。",
                    "human_core": "真相和想搶功、想插隊、想替自己鋪路有關。",
                },
                {
                    "name": "替朋友出氣型",
                    "setup": "有人不是為了自己，而是因為朋友被笑、被排擠、被看不起，偷偷做了一點手腳想替朋友扳回來。",
                    "pressure": "那個小動作可能會害別人錯失機會、差點受傷、差點錯過流程，現場很快就變嚴重。",
                    "mislead": "先讓大家以為只是普通惡作劇，後來才發現裡面夾著替朋友抱不平的情緒。",
                    "human_core": "真相和義氣、偏心、替朋友出氣、把小委屈越想越大有關。",
                },
                {
                    "name": "惡作劇過頭型",
                    "setup": "有人本來只想鬧一下、嚇一下、拖一下，卻沒想到後果比自己預想的大很多。",
                    "pressure": "事情可能差點害人受傷、錯過車次、打翻熱東西、衝撞人群或讓整場流程停住。",
                    "mislead": "先讓人覺得這只是小玩笑，後來才看到原來那一下已經把事情推到很危險的邊緣。",
                    "human_core": "真相和幼稚、想逞一時快意、低估後果有關。",
                },
                {
                    "name": "貪心占便宜型",
                    "setup": "有人不是為了報復，而是想多拿一點、搶前面、卡到更好的位置或獎勵，才偷偷亂動規則邊緣的東西。",
                    "pressure": "那點小貪心會連帶害別人沒位置、沒資格、沒裝備，甚至差點發生危險。",
                    "mislead": "先讓人以為他只是手腳快，後來才看出他根本一直在偷挪、偷藏、偷改。",
                    "human_core": "真相和貪心、想佔便宜、覺得『一下下應該沒差』有關。",
                },
                {
                    "name": "報復破壞型",
                    "setup": "有人不是只想鬧一下，而是真的氣不過，故意去動別人的道具、設備或安全安排。",
                    "pressure": "一旦成功，不只會害人難堪，還可能讓東西壞掉、流程停擺，甚至差點害人受傷。",
                    "mislead": "先讓大家以為是現場忙亂弄壞的，後來才發現某個人早就帶著不爽和報復心在靠近關鍵物件。",
                    "human_core": "真相和報復、嫉妒、想讓別人也吃一次苦頭有關。",
                },
                {
                    "name": "危險邊緣型",
                    "setup": "有人逞強、愛現或想幫朋友扳回一城，先動了一個『應該不會怎樣吧』的小手腳。",
                    "pressure": "那個小手腳把事情推到差點受傷、差點燙到、差點砸壞設備或整個流程被迫喊停的邊緣。",
                    "mislead": "先讓大家覺得只是小亂子，後來才從被拉住的人、差點倒下的東西、被喊停的流程看出嚴重性。",
                    "human_core": "真相和低估後果、愛逞強、想出一口氣有關。",
                },
            ]

        if self.incident_shape_cards is None:
            self.incident_shape_cards = [
                {
                    "name": "流程卡住",
                    "shape": "不是單純少一樣東西，而是某個安排卡住了：上台順序、評分、報到、闖關、廣播、展示全被拖住。",
                    "drift_guard": "如果最後只剩『東西不見』，就還不夠；要把流程壓力、人群視線、來不及的焦躁寫出來。",
                },
                {
                    "name": "說法互撞",
                    "shape": "兩個以上的人都說得像真的，但彼此其實兜不起來，事件是從矛盾說法裡慢慢長出來的。",
                    "drift_guard": "重點不是找東西，是誰故意漏講、誰把時間講歪、誰怕講真話會丟臉。",
                },
                {
                    "name": "順序或名單亂掉",
                    "shape": "不是誰偷了東西，而是上場順序、報到名單、評分結果或工作分配忽然對不上，讓大家開始互相懷疑誰亂動過。",
                    "drift_guard": "重點是誰改過、誰記錯、誰嘴硬不承認，不要最後只剩一張紙放錯地方。",
                },
                {
                    "name": "誤傳公告",
                    "shape": "一句被講歪的提醒、廣播或耳語，把整群人帶去錯的方向，還害某個人看起來很像做了壞事。",
                    "drift_guard": "故事要靠人傳人越傳越歪，不是靠地上撿到一個小東西往前推。",
                },
                {
                    "name": "公開出糗被遮",
                    "shape": "有人快要在公開場合出糗，於是偷偷遮掩，結果把別人一起拖進誤會。",
                    "drift_guard": "事件的核心是難堪、逞強、怕被笑，不是單純失物。",
                },
                {
                    "name": "好心幫倒忙",
                    "shape": "有人原本想偷偷幫忙、想補救，結果越補越亂，還讓現場以為出了更大的事。",
                    "drift_guard": "不要把它寫成溫吞的小誤會，要讓補救行為真的扯亂場面。",
                },
                {
                    "name": "傳話走樣",
                    "shape": "一段被傳歪的話、公告、提醒或耳語，把大家的注意力整個帶錯。",
                    "drift_guard": "故事要靠人傳人帶來的偏差往前，不是靠地上小東西推進。",
                },
                {
                    "name": "被懷疑作弊或搶位",
                    "shape": "有人看起來像插隊、搶名額、作弊、偷改結果或故意卡別人，讓全場情緒一下子偏向某個對象。",
                    "drift_guard": "不要只寫成單純誤會，還要把那個人為什麼不敢馬上講清楚寫出來。",
                },
                {
                    "name": "臨時換位或頂替",
                    "shape": "有人臨時替別人上場、換工作、換位置，本來是想救火，結果讓說法和目擊畫面全都對不起來。",
                    "drift_guard": "關鍵是救火帶來的混亂與遮掩，不是單純『剛好站錯地方』。",
                },
                {
                    "name": "調包或拿錯背後有苦衷",
                    "shape": "可以有調包、拿錯、放錯，但背後一定要連著更大的情緒或苦衷，例如怕被罵、怕難堪、怕連累別人。",
                    "drift_guard": "如果只是機械地拿錯了，就不夠像樣本；要把為什麼不敢馬上講出來寫清楚。",
                },
                {
                    "name": "偷偷藏起來",
                    "shape": "有人把關鍵物件、名單、證明、服裝、道具偷偷藏起來，想拖慢別人、害別人丟臉，或替自己爭出一條路。",
                    "drift_guard": "不要把它洗成單純忘記放哪；要讓藏起來這件事本身帶著情緒、目的或不甘心。",
                },
                {
                    "name": "故意偷改順序或標記",
                    "shape": "有人故意改動名單、號碼、順位、標籤或路線，想讓別人錯位、遲到、被誤會，自己或朋友就能佔便宜。",
                    "drift_guard": "重點不是紙張本身，而是誰想讓誰吃虧、為什麼要偷偷改，和被發現後怎麼硬撐。",
                },
                {
                    "name": "搶風頭害人出糗",
                    "shape": "有人為了搶表現、搶舞台、搶注意力，故意讓另一個人臨場出包，看起來像自己比較厲害。",
                    "drift_guard": "不要最後只剩『誤會』；要有明確的小壞心眼和主動動手的痕跡。",
                },
                {
                    "name": "報復式惡作劇",
                    "shape": "有人因為先前的不爽、輸了不甘心、被笑過或被搶位，於是趁活動混亂時故意搞一個不大不小、但足以讓人出糗的惡作劇。",
                    "drift_guard": "尺度可以兒童向，但不能只剩小失手；要讓那股『我就是故意要你難看一下』的心態存在。",
                },
                {
                    "name": "惡作劇差點釀成危險",
                    "shape": "一個原本只是想拖人一下、嚇人一下、整人一下的惡作劇，差點讓人跌倒、燙到、錯過列車、撞到舞台、衝進危險區。",
                    "drift_guard": "重點不是實際受重傷，而是大家突然意識到『這已經不是小玩笑了』，最後要由大人接手穩住。",
                },
                {
                    "name": "藏起關鍵物品害人卡關",
                    "shape": "有人偷偷把關鍵物品、票券、名牌、裝備、號碼牌、路線圖藏起來，本來只想卡別人一下，結果差點害人錯過大流程或進到不安全的狀況。",
                    "drift_guard": "不要只收成『藏起來又拿出來』；要寫出它差點造成的更大後果，以及大人如何介入處理。",
                },
                {
                    "name": "破壞道具或設備",
                    "shape": "有人故意或半故意去動表演道具、麥克風線、裝飾、器材、房卡、票券或安全物件，結果不只害流程亂掉，還差點讓東西壞掉或害人受傷。",
                    "drift_guard": "不要只寫成『東西壞了』；要寫出誰動過、為什麼動、差點造成什麼實際衝擊，以及大人怎麼立刻接手。",
                },
                {
                    "name": "安全動線被搞亂",
                    "shape": "有人把指示、號碼、方向牌、安全線或排隊動線偷偷改掉，本來想害別人出糗或拖慢，結果差點讓人撞上、絆倒、誤闖危險區，整個流程一度停擺。",
                    "drift_guard": "重點是它真的差點出事，不只是大家跑錯邊；一定要寫出實際危險邊緣和大人接手穩場。",
                },
                {
                    "name": "惡意弄壞重要物件",
                    "shape": "有人把服裝、裝備、展示品、餐點、名牌或關鍵道具弄髒、弄壞、泡濕、扯裂，想讓別人上不了場或當場難堪。",
                    "drift_guard": "不要只剩『東西壞掉』；要把做壞事的人當時的氣、嫉妒或報復心，以及差點擴大的現場後果寫出來。",
                },
            ]

        if self.banned_proper_nouns is None:
            self.banned_proper_nouns = [
                "千羽會",
                "亨利爵士",
                "孔雀",
                "喵喵（粉絲）",
                "老鷹大翔",
            ]

        # ✅ 開場不再硬禁自然事件詞；只擋直接進入破案 / 審訊語氣
        if self.incident_terms_for_opening_ban is None:
            self.incident_terms_for_opening_ban = []

        if self.forbidden_opening_terms is None:
            self.forbidden_opening_terms = [
                "開始調查",
                "推理",
                "真相",
                "嫌疑",
                "嫌疑人",
                "犯人",
                "兇手",
                "審問",
                "審訊",
                "解決案件",
                "破案",
            ]

        if self.banned_placeholders is None:
            self.banned_placeholders = [
                "學長A",
                "學長B",
                "學長C",
                "嫌疑人A",
                "嫌疑人B",
                "嫌疑人C",
                "嫌疑人甲",
                "嫌疑人乙",
                "嫌疑人丙",
            ]

        if self.placeholder_role_regex_patterns is None:
            role_prefix = (
                "老師|爸爸|媽媽|叔叔|阿姨|哥哥|姊姊|店員|志工|家長|工作人員|"
                "主持人|裁判|評審|老闆|司機|站務員|保全|醫生|護士|同學|孩子"
            )
            self.placeholder_role_regex_patterns = [
                rf"(?<![\u4e00-\u9fffA-Za-z0-9_])(?:{role_prefix})[A-ZＡ-Ｚ]",
                rf"(?<![\u4e00-\u9fffA-Za-z0-9_])(?:{role_prefix})[甲乙丙丁戊己庚辛壬癸]",
                rf"(?<![\u4e00-\u9fffA-Za-z0-9_])(?:{role_prefix})\d+",
            ]

        if self.banned_generics is None:
            self.banned_generics = [
                "紅色衣服",
                "那個男孩",
                "某位同學",
                "穿外套的人",
                "小朋友",
                "那個人",
            ]

        # ✅ 重要：這個詞太常用、且不一定代表「沒名字的配角」
        #（例如：店員喊「小朋友們小心」是自然台詞；留著會讓成功率大幅下降）
        self.banned_generics = [x for x in (self.banned_generics or []) if x != "小朋友"]

        if self.generic_side_speaker_labels is None:
            self.generic_side_speaker_labels = [
                "老師",
                "爸爸",
                "媽媽",
                "叔叔",
                "阿姨",
                "哥哥",
                "姊姊",
                "店員",
                "大人",
                "家長",
                "志工",
                "工作人員",
                "主持人",
                "裁判",
                "評審",
                "老闆",
                "司機",
                "站務員",
                "保全",
                "醫生",
                "護士",
                "同學",
            ]

        if self.gamey_patterns is None:
            self.gamey_patterns = [
                "你覺得該怎麼辦",
                "你會怎麼做",
                "請選擇",
                "玩家",
                "如果你在這裡",
            ]

        if self.banned_reader_hint_patterns is None:
            # ✅ 全篇禁：不要幫讀者「整理/記住/排除」的教學式總結
            self.banned_reader_hint_patterns = [
                "幫你整理",
                "我幫你整理",
                "我們幫你整理",
                "重點是",
                "重點整理",
                "整理重點",
                "請記住",
                "你要記住",
                "記得這些",
                "把這些記起來",
                "線索總結",
                "線索整理",
                "現在我們把線索整理",
                "因此可以排除",
                "所以可以排除",
                "我們排除",
                "這就排除",
                "答案就是",
                "正確答案是",
                "總結一下",
                "整理一下線索",
                "所以答案是",
                "結論是",
                "換句話說",
            ]

        if self.banned_generic_prose_patterns is None:
            self.banned_generic_prose_patterns = [
                "在陽光燦爛的午後",
                "熱鬧非凡",
                "熱鬧得像一個大派對",
                "忙得不可開交",
                "四處都是笑聲和叫喊聲",
                "充滿了一種",
                "充滿著一種",
                "無憂無慮的氣氛",
                "不由得",
                "瞬間變得緊張",
                "瞬間安靜下來",
                "眼睛閃閃發亮",
                "眼裡閃爍著",
                "讓人忍不住想笑",
                "讓人不自主地想",
                "眉眼間迸發出一絲靈光",
                "親密地跟在她身後",
                "氣勢洶洶地指揮",
                "各種各樣",
                "笑聲不斷",
                "心情愉悅",
                "迫不及待想",
                "讓人感到溫暖",
                "感受到彼此的快樂",
                "今天會有什麼有趣的事情發生",
                "今天會是個特別的日子",
                "這真是一個美好的日子",
                "每一天都充滿歡樂",
            ]

        if self.generic_prose_regex_patterns is None:
            self.generic_prose_regex_patterns = [
                r"充滿了[^。！？\n]{0,12}氣氛",
                r"充滿著[^。！？\n]{0,12}氣氛",
                r"讓人[^。！？\n]{0,10}感到溫暖",
            ]

        if self.opening_overview_regex_patterns is None:
            self.opening_overview_regex_patterns = [
                r"從[^。！？\n]{0,12}到[^。！？\n]{0,12}都",
                r"到處都是[^。！？\n]{0,12}",
                r"^旁白：一年一度的[^。！？\n]{0,26}(今天正式開始|正式登場|今天開始)",
            ]

        if self.ending_moralizing_patterns is None:
            self.ending_moralizing_patterns = [
                "大家學到",
                "學到了",
                "團隊溝通的重要性",
                "這次插曲變成了大家的提醒",
                "大家從這次",
                "成為大家的提醒",
            ]

        if self.ending_moralizing_regex_patterns is None:
            self.ending_moralizing_regex_patterns = [
                r"大家[^。！？\n]{0,12}學到",
                r"學到[^。！？\n]{0,12}(重要性|道理|一課)",
                r"這次[^。！？\n]{0,14}(提醒|教訓)",
            ]

        if self.arrival_context_markers is None:
            self.arrival_context_markers = [
                "爸媽",
                "家人",
                "全家",
                "校外教學",
                "跟著",
                "跟爸媽",
                "跟媽媽",
                "跟爸爸",
                "跟老師",
                "帶我",
                "帶我們",
                "來玩",
                "來住",
                "來參加",
                "來比賽",
                "來闖關",
                "來度假",
                "住進",
                "住一晚",
                "旅行",
                "出來玩",
                "報名",
                "住客",
                "房客",
                "今天來",
                "我們今天",
                "今天跟",
                "集合",
                "報到",
            ]

        if self.arrival_context_regex_patterns is None:
            self.arrival_context_regex_patterns = [
                r"(爸爸|媽媽|爸媽|家人|全家)[^。！？\n]{0,10}(帶|陪|載|拉|領|拖|跟)",
                r"(老師|班上|同學)[^。！？\n]{0,12}(帶|領|集合|報到|校外教學|闖關|來參加)",
                r"(我們|今天)[^。！？\n]{0,12}(來玩|來住|來參加|來幫忙|來報名|來比賽|來闖關|來旅行|來度假)",
                r"(住客|房客|旅客|家長)[^。！？\n]{0,10}(報到|集合|進場|準備)",
                r"(跟著|跟)[^。！？\n]{0,8}(爸爸|媽媽|爸媽|家人|老師|同學)",
            ]

        if self.admission_markers is None:
            self.admission_markers = [
                "我的疏忽",
                "我的錯",
                "都是我",
                "是我的錯",
                "剛剛太忙了",
                "我剛剛太忙",
                "我剛剛沒注意",
            ]

        if self.admission_action_markers is None:
            self.admission_action_markers = [
                "把",
                "拿",
                "貼",
                "搬",
                "放",
                "弄",
                "塞",
                "換",
                "翻",
                "蓋",
                "抹",
                "推",
                "壓",
                "撕",
                "排",
                "寫",
                "念",
                "發",
                "送",
                "按",
                "刷",
                "登記",
                "貼錯",
                "拿錯",
                "放錯",
                "寫錯",
                "排錯",
                "送錯",
                "叫錯",
                "報錯",
                "喊錯",
                "播錯",
                "搞混",
                "結果",
                "差點",
                "害得",
                "所以",
            ]

        if self.relationship_grounding_markers is None:
            self.relationship_grounding_markers = [
                "同學",
                "同班",
                "隔壁班",
                "朋友",
                "隊友",
                "搭檔",
                "對手",
                "助理",
                "負責",
                "幫忙",
                "去年冠軍",
                "上一屆",
                "班導",
                "老師",
                "站務員",
                "站長",
                "志工",
                "主持人",
                "主廚",
                "評審",
                "參賽",
                "旅客",
                "乘客",
                "鄰居",
                "表哥",
                "表姊",
                "家長",
                "老闆",
                "攤主",
                "工作人員",
                "導覽員",
                "領隊",
                "隊長",
                "班長",
                "服務台",
                "報到桌",
                "住客",
                "房客",
                "來賓",
                "親子",
            ]

        if self.bigger_consequence_markers is None:
            self.bigger_consequence_markers = [
                "差點",
                "差一點",
                "危險",
                "拉住",
                "攔住",
                "趕緊",
                "趕快",
                "停住",
                "停下",
                "暫停",
                "全場",
                "亂成一團",
                "衝進",
                "闖進",
                "撞到",
                "滑倒",
                "跌倒",
                "摔",
                "燙",
                "打翻",
                "熱湯",
                "熱飲",
                "來不及",
                "錯過",
                "禁區",
                "危險區",
                "出入口",
                "護欄",
                "繩索",
                "受傷",
            ]

        if self.adult_takeover_markers is None:
            self.adult_takeover_markers = [
                "帶去了解",
                "帶到旁邊",
                "拉到旁邊",
                "先帶開",
                "先帶離",
                "帶離現場",
                "請家長",
                "通知家長",
                "交給大人",
                "大人接手",
                "接手處理",
                "安撫",
                "說明後續",
                "先把人帶開",
                "先把孩子帶開",
                "先去旁邊",
            ]

        if self.banned_accuse_tone_patterns is None:
            self.banned_accuse_tone_patterns = [
                "你是不是",
                "是不是你",
                "要不要承認",
                "你根本",
                "就是你",
                "你為什麼都不",
                "隨便甩掉",
            ]

        if self.incident_flat_resolution_patterns is None:
            self.incident_flat_resolution_patterns = [
                "謝謝你們的關心",
                "回到了熱鬧的氛圍",
                "情緒又回到了熱鬧的氛圍",
                "今天會是個特別的日子",
                "這真是一個美好的日子",
                "讓每一天都充滿歡樂",
            ]

        if self.opening_safe_patterns is None:
            # ✅ 重要：不得包含 incident_terms_for_opening_ban / forbidden_opening_terms
            self.opening_safe_patterns = [
                "旁白：舞台那頭在試音，服務台這頭在對名單，整個場子像每個角落都在同時喊人。",
                "霏霏：你先把嘴巴擦乾淨，再說你有在幫忙。",
                "樂樂：我有啊，我是在幫大家試吃。",
                "林老師：先來領號碼牌，不要領完就塞進口袋最深的地方。",
                "旁白：旁邊的人抱著海報、點心箱和道具跑來跑去，誰都說自己只是先借一步。",
                "廣播阿姨阿秀：這個先放我這裡，等一下我一定記得還。",
                "霏霏：你剛剛不是說沒事，怎麼現在又跑得像鞋底著火。",
                "樂樂：因為今天大家都很忙，我只好跟著忙一下。",
                "旁白：廣播一響，排隊的人群和後台的人同時回頭，像整個活動一起抖了一下。",
                "樂樂的爸爸：先把人、東西和順序都顧好，等一下才不會一團亂。",
            ]

    # ============================================================
    # Prompt loading
    # ============================================================

    def _read(self, p: Path) -> str:
        return p.read_text(encoding="utf-8").strip()

    def _asset_map(self, *, include_old_rival: bool) -> Dict[str, str]:
        assets = {
            "story_prompt_v1.md": STORY_PROMPT_V1_MD,
            "schema_story_nodes.md": SCHEMA_STORY_NODES_MD,
            "guard_rules.md": GUARD_RULES_MD,
            "story_response_whitelist.md": STORY_RESPONSE_WHITELIST_MD,
        }
        if include_old_rival:
            assets["world_old_rival_module.md"] = WORLD_OLD_RIVAL_MODULE_MD
        return assets

    def _load_prompt_text(self, name: str, *, include_old_rival: bool) -> str:
        fp = self.prompts_dir / name
        if fp.exists():
            return self._read(fp)
        return self._asset_map(include_old_rival=include_old_rival).get(name, "").strip()

    def load_story_prompt_text(self) -> str:
        return self._load_prompt_text("story_prompt_v1.md", include_old_rival=False)

    def build_instructions(self, *, include_old_rival: bool) -> str:
        blocks: list[str] = []

        for name in self.core_files:
            text = self._load_prompt_text(name, include_old_rival=include_old_rival)
            if text:
                blocks.append(f"\n\n# FILE: {name}\n{text}")

        return "\n".join(blocks).strip()

    # ============================================================
    # Theme
    # ============================================================

    def pick_theme(self, seed: Optional[int], nonce: str) -> str:
        if not self.allowed_background_themes:
            return ""
        base = f"{seed if seed is not None else 'null'}:{nonce}"
        h = int(hashlib.sha1(base.encode("utf-8")).hexdigest(), 16)
        return self.allowed_background_themes[h % len(self.allowed_background_themes)]

    def theme_grounding_hint(self, theme: str) -> str:
        if not theme:
            return ""
        return str((self.theme_grounding_hints or {}).get(theme, "")).strip()

    def pick_story_engine(self, seed: Optional[int], nonce: str) -> Dict[str, Any]:
        cards = self.story_engine_cards or []
        if not cards:
            return {}
        weights = {
            "搶風頭搞事型": 4,
            "嫉妒動手型": 4,
            "假幫忙真搞鬼型": 4,
            "惡作劇過頭型": 5,
            "替朋友出氣型": 3,
            "貪心占便宜型": 3,
            "報復破壞型": 5,
            "危險邊緣型": 5,
            "兩層誤會型": 2,
            "說半套型": 2,
        }
        weighted_cards: list[Dict[str, Any]] = []
        for card in cards:
            name = str(card.get("name") or "").strip()
            weighted_cards.extend([card] * max(1, int(weights.get(name, 1))))
        cards = weighted_cards or cards
        base = f"engine:{seed if seed is not None else 'null'}:{nonce}"
        h = int(hashlib.sha1(base.encode("utf-8")).hexdigest(), 16)
        return dict(cards[h % len(cards)])

    def pick_incident_shape(self, seed: Optional[int], nonce: str) -> Dict[str, Any]:
        cards = self.incident_shape_cards or []
        if not cards:
            return {}
        weights = {
            "偷偷藏起來": 3,
            "故意偷改順序或標記": 2,
            "搶風頭害人出糗": 4,
            "報復式惡作劇": 5,
            "惡作劇差點釀成危險": 6,
            "藏起關鍵物品害人卡關": 4,
            "破壞道具或設備": 6,
            "安全動線被搞亂": 6,
            "惡意弄壞重要物件": 6,
            "被懷疑作弊或搶位": 1,
            "誤傳公告": 2,
        }
        weighted_cards: list[Dict[str, Any]] = []
        for card in cards:
            name = str(card.get("name") or "").strip()
            weighted_cards.extend([card] * max(1, int(weights.get(name, 1))))
        cards = weighted_cards or cards
        base = f"incident:{seed if seed is not None else 'null'}:{nonce}"
        h = int(hashlib.sha1(base.encode("utf-8")).hexdigest(), 16)
        return dict(cards[h % len(cards)])

    # ============================================================
    # Text helpers
    # ============================================================

    def split_paragraphs(self, narration: str) -> list[str]:
        return [x.strip() for x in (narration or "").split("\n\n") if x.strip()]

    def collect_narration_text(self, nodes: Dict[str, Any]) -> str:
        chunks: list[str] = []
        for _nid, node in (nodes or {}).items():
            if not isinstance(node, dict):
                continue
            nar = node.get("narration")
            if isinstance(nar, str):
                chunks.append(nar)
        return "\n".join(chunks)

    def opening_paragraphs(self, nodes: Dict[str, Any]) -> int:
        s1 = nodes.get("scene_01_start")
        s1_nar = str(s1.get("narration") or "") if isinstance(s1, dict) else ""
        return len(self.split_paragraphs(s1_nar))

    def pre_incident_paragraphs(self, nodes: Dict[str, Any]) -> int:
        total = 0
        for nid in ("scene_01_start", "scene_01_warmup_2", "scene_01_warmup_3"):
            total += len(self.split_paragraphs(self._node_narration(nodes, nid)))
        return total

    def pre_incident_text(self, nodes: Dict[str, Any]) -> str:
        parts: list[str] = []
        for nid in ("scene_01_start", "scene_01_warmup_2", "scene_01_warmup_3"):
            nar = self._node_narration(nodes, nid)
            if nar:
                parts.append(nar)
        return "\n".join(parts)

    def _opening_banned_all(self) -> List[str]:
        # scene_01_start 全禁：事件字眼 + 推理/異常口吻字眼
        return list(
            dict.fromkeys(
                (self.incident_terms_for_opening_ban or [])
                + (self.forbidden_opening_terms or [])
            )
        )

    def _has_any_opening_banned(self, text: str) -> List[str]:
        hits: List[str] = []
        for w in self._opening_banned_all():
            if w and (w in (text or "")):
                hits.append(w)
        return hits

    def _has_any_reader_hint_banned(self, text: str) -> List[str]:
        hits: List[str] = []
        t = text or ""
        for w in self.banned_reader_hint_patterns or []:
            if w and (w in t):
                hits.append(w)
        return hits

    def _placeholder_like_hits(self, text: str) -> List[str]:
        hits: List[str] = []
        t = text or ""

        for w in self.banned_placeholders or []:
            if w and (w in t):
                hits.append(w)

        for pat in self.placeholder_role_regex_patterns or []:
            try:
                for m in re.finditer(pat, t):
                    val = str(m.group(0) or "").strip()
                    if val:
                        hits.append(val)
            except re.error:
                continue

        return list(dict.fromkeys(hits))

    def _generic_speaker_label_hits(self, text: str) -> List[str]:
        hits: List[str] = []
        for para in self.split_paragraphs(text or ""):
            m = re.match(r"^([^：:\n]{1,16})[：:]", para)
            if not m:
                continue
            speaker = self._speaker_label_base_name(str(m.group(1) or ""))
            if speaker in (self.generic_side_speaker_labels or []):
                hits.append(speaker)
        return list(dict.fromkeys(hits))

    def _speaker_label_base_name(self, text: str) -> str:
        t = str(text or "").strip()
        t = re.sub(r"[（(][^）)]*[）)]$", "", t).strip()
        return t

    def _name_is_too_generic_or_placeholder(self, text: str) -> bool:
        t = str(text or "").strip()
        if not t:
            return False
        if t in (self.banned_generics or []):
            return True
        if t in (self.generic_side_speaker_labels or []):
            return True
        if t in (self.banned_placeholders or []):
            return True
        for pat in self.placeholder_role_regex_patterns or []:
            try:
                if re.search(pat, t):
                    return True
            except re.error:
                continue
        return False

    def _opening_overview_hits(self, text: str) -> List[str]:
        first_para = self.split_paragraphs(text or "")
        if not first_para:
            return []
        p0 = first_para[0]
        hits: List[str] = []
        for pat in self.opening_overview_regex_patterns or []:
            try:
                if re.search(pat, p0):
                    hits.append(pat)
            except re.error:
                continue
        if (
            re.match(r"^旁白：今天[^。！？\n]{0,40}(正在舉辦|是|是一年一度)", p0)
            and p0.count("，") >= 3
        ):
            hits.append("今天活動總覽起手")
        if (
            (p0.startswith("旁白：一年一度的") or p0.startswith("旁白：今天是一年一度的") or p0.startswith("旁白：今晚是一年一度的"))
            and not any(mark in p0 for mark in ["霏霏", "樂樂", "爸爸", "媽媽", "同學", "老師", "阿姨阿", "叔叔阿"])
            and "「" not in p0
            and "」" not in p0
        ):
            hits.append("一年一度活動口播起手")
        return hits

    def _opening_person_action_ok(self, text: str) -> bool:
        first_para = self.split_paragraphs(text or "")
        if not first_para:
            return False
        p0 = first_para[0]
        human_tokens = [
            "霏霏",
            "樂樂",
            "爸爸",
            "媽媽",
            "老師",
            "阿姨",
            "叔叔",
            "同學",
            "志工",
            "工作人員",
            "主持人",
            "站務員",
            "老闆",
            "家長",
        ]
        action_tokens = [
            "忙",
            "衝",
            "跑",
            "扛",
            "拉",
            "抱",
            "揮",
            "喊",
            "擦",
            "找",
            "追",
            "擠",
            "搬",
            "端",
            "塞",
            "掉",
            "滑",
            "喘",
            "翻",
            "拽",
            "蹲",
            "跳",
        ]
        has_human = any(token in p0 for token in human_tokens)
        has_action = any(token in p0 for token in action_tokens)
        return has_human and has_action

    def _memorable_name_style_hits(self, nodes: Dict[str, Any]) -> List[str]:
        hits: list[str] = []
        for name in self._collect_preaccuse_named_cast(nodes):
            base = self._speaker_label_base_name(name)
            if not base or base in {"旁白", "霏霏", "樂樂"}:
                continue
            if self._name_is_too_generic_or_placeholder(base):
                continue
            if re.search(r"阿[\u4e00-\u9fff]{1,3}", base):
                hits.append(base)
                continue
            if re.search(r"[\u4e00-\u9fff]{1,4}小[\u4e00-\u9fff]{1,3}", base):
                hits.append(base)
                continue
            if re.search(r"([\u4e00-\u9fff])\1", base):
                hits.append(base)
                continue
        return sorted(dict.fromkeys(hits))

    def _queue_dispute_hits(self, nodes: Dict[str, Any]) -> int:
        blob = "\n".join(
            [
                self._node_narration(nodes, self.incident_node_id),
                self._node_narration(nodes, "scene_03_check_1"),
                self._node_narration(nodes, "scene_04_check_2"),
                self._node_narration(nodes, "scene_05_check_3"),
                self._node_narration(nodes, "scene_06_hypothesis_1"),
            ]
        )
        marks = [
            "排隊",
            "插隊",
            "換位置",
            "換位",
            "順序",
            "順位",
            "搶先",
            "排回",
            "隊伍",
            "號碼牌",
            "先進去",
        ]
        return min(sum(blob.count(mark) for mark in marks if mark in blob), 199)

    def _opening_arrival_context_hits(self, text: str) -> List[str]:
        head = "\n".join(self.split_paragraphs(text or "")[:5])
        if not head:
            return []
        hits: List[str] = []
        for pat in self.arrival_context_regex_patterns or []:
            try:
                if re.search(pat, head):
                    hits.append(f"regex:{pat}")
            except re.error:
                continue
        for w in self.arrival_context_markers or []:
            if w and (w in head):
                hits.append(w)
        return list(dict.fromkeys(hits))

    def _ungrounded_admission_paras(self, text: str) -> List[str]:
        paras = self.split_paragraphs(text or "")
        bad: List[str] = []
        for idx, para in enumerate(paras):
            if not any(marker and (marker in para) for marker in (self.admission_markers or [])):
                continue
            context_parts = [para]
            if idx > 0:
                context_parts.insert(0, paras[idx - 1])
            context = "\n".join(context_parts)
            if any(marker and (marker in context) for marker in (self.admission_action_markers or [])):
                continue
            snippet = para.replace("\n", " ").strip()
            if len(snippet) > 40:
                snippet = snippet[:40] + "..."
            bad.append(snippet)
        return bad

    def _ending_moralizing_hits(self, text: str) -> List[str]:
        t = text or ""
        hits: List[str] = [p for p in (self.ending_moralizing_patterns or []) if p in t]
        for pat in self.ending_moralizing_regex_patterns or []:
            try:
                if re.search(pat, t):
                    hits.append(f"regex:{pat}")
            except re.error:
                continue
        return list(dict.fromkeys(hits))

    def _wrongdoing_scale_report(self, text: str) -> Dict[str, int]:
        blob = text or ""
        sneaky_marks = [
            "故意",
            "偷偷",
            "藏起來",
            "藏了",
            "偷改",
            "改掉",
            "換掉",
            "調包",
            "塞進",
            "挪走",
            "亂動",
            "動手腳",
            "栽贓",
            "嫁禍",
            "報復",
            "嫉妒",
            "搶風頭",
            "不想讓",
            "不讓",
            "想害",
            "害他",
            "害她",
            "假裝",
            "裝作",
            "說謊",
            "漏講",
            "遮",
            "擋",
            "卡住",
        ]
        accident_marks = [
            "不小心",
            "沒注意",
            "太急",
            "手忙腳亂",
            "搞混",
            "拿錯",
            "放錯",
            "只是想幫忙",
            "原本想幫忙",
            "不是故意",
            "一時",
            "慌",
            "補救",
            "越幫越亂",
            "失手",
            "我的疏忽",
            "我的錯",
        ]
        sneaky_hits = sum(blob.count(mark) for mark in sneaky_marks if mark in blob)
        accident_hits = sum(blob.count(mark) for mark in accident_marks if mark in blob)
        return {
            "sneaky_wrongdoing_hits": min(sneaky_hits, 199),
            "accident_softener_hits": min(accident_hits, 199),
        }

    def _ambiguity_hits(self, text: str) -> int:
        marks = [
            "好像",
            "像是",
            "也可能",
            "可能",
            "不一定",
            "說不準",
            "或許",
            "看起來",
            "不敢肯定",
            "未必",
        ]
        blob = text or ""
        return min(sum(blob.count(mark) for mark in marks if mark in blob), 199)

    def _cast_grounding_hits(self, text: str) -> int:
        markers = [
            "同學",
            "同班",
            "隔壁班",
            "隊友",
            "搭檔",
            "去年冠軍",
            "上一屆",
            "班導",
            "老師",
            "站務員",
            "站長",
            "志工",
            "主持人",
            "主廚",
            "評審",
            "參賽",
            "旅客",
            "乘客",
            "鄰居",
            "朋友",
            "表哥",
            "表姊",
            "家長",
            "老闆",
            "攤主",
        ]
        blob = text or ""
        return min(sum(blob.count(mark) for mark in markers if mark in blob), 199)

    def _speaker_label_is_self_grounded(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        self_grounded_tokens = [
            "老師",
            "爸爸",
            "媽媽",
            "阿姨",
            "叔叔",
            "站務員",
            "站長",
            "志工",
            "主持人",
            "評審",
            "裁判",
            "老闆",
            "店長",
            "主廚",
            "保全",
            "司機",
            "醫生",
            "護士",
            "工作人員",
            "家長",
        ]
        return any(token in name for token in self_grounded_tokens)

    def _collect_preaccuse_named_cast(self, nodes: Dict[str, Any]) -> List[str]:
        blob = self._pre_accuse_text_blob(nodes)
        paras = self.split_paragraphs(blob)
        default_speakers = {"旁白", "霏霏", "樂樂"}
        names: set[str] = set()

        for p in paras:
            m = re.match(r"^([^：:\n]{1,12})[：:]", p)
            if not m:
                continue
            speaker = self._speaker_label_base_name(m.group(1))
            if speaker and speaker not in default_speakers:
                names.add(speaker)

        for s in self._final_accuse_choices(nodes)[:3]:
            s = (s or "").strip()
            if s:
                names.add(s)

        return sorted(names)

    def _first_appearance_grounding_issues(self, nodes: Dict[str, Any]) -> List[str]:
        paras = self.split_paragraphs(self._pre_accuse_text_blob(nodes))
        if not paras:
            return []

        issues: list[str] = []
        markers = self.relationship_grounding_markers or []
        for name in self._collect_preaccuse_named_cast(nodes):
            if not name:
                continue
            if self._name_is_too_generic_or_placeholder(name):
                continue
            if self._speaker_label_is_self_grounded(name):
                continue

            first_idx = -1
            for idx, para in enumerate(paras):
                if name in para:
                    first_idx = idx
                    break
            if first_idx < 0:
                continue

            # 允許先用旁白或前一段交代關係，再接角色開口。
            window = "\n".join(paras[max(0, first_idx - 1) : first_idx + 1])
            if any(mark in window for mark in markers):
                continue
            issues.append(name)

        return issues[:6]

    def _stakes_scale_report(self, nodes: Dict[str, Any]) -> Dict[str, int]:
        consequence_blob = "\n".join(
            [
                self._node_narration(nodes, self.incident_node_id),
                self._node_narration(nodes, "scene_03_check_1"),
                self._node_narration(nodes, "scene_04_check_2"),
                self._node_narration(nodes, "scene_05_check_3"),
                self._node_narration(nodes, "scene_06_hypothesis_1"),
            ]
        )
        ending_blob = "\n".join(
            [
                self._node_narration(nodes, "scene_10_ending_clear"),
                self._node_narration(nodes, "scene_10_ending_nudge"),
                self._node_narration(nodes, "scene_10_ending_defer"),
            ]
        )
        consequence_hits = sum(
            consequence_blob.count(mark)
            for mark in (self.bigger_consequence_markers or [])
            if mark in consequence_blob
        )
        adult_hits = sum(
            ending_blob.count(mark)
            for mark in (self.adult_takeover_markers or [])
            if mark in ending_blob
        )
        return {
            "bigger_consequence_hits": min(consequence_hits, 199),
            "adult_takeover_hits": min(adult_hits, 199),
        }

    def _late_flip_hits(self, nodes: Dict[str, Any]) -> int:
        blob = "\n".join(
            [
                self._node_narration(nodes, "scene_05_check_3"),
                self._node_narration(nodes, "scene_06_hypothesis_1"),
            ]
        )
        marks = [
            "另一個方向",
            "另一種可能",
            "同時間",
            "但同時",
            "但也",
            "也可能",
            "或者",
            "還有一個可能",
            "不只",
            "兩條說法",
            "兩種解釋",
            "都還不完整",
            "說得通",
            "翻掉",
        ]
        return min(sum(blob.count(mark) for mark in marks if mark in blob), 199)

    def _pre_incident_dialogue_hits(self, nodes: Dict[str, Any]) -> Dict[str, int]:
        paras = self.split_paragraphs(self.pre_incident_text(nodes))
        total_dialogue = 0
        sibling_dialogue = 0
        for para in paras:
            m = re.match(r"^([^：:\n]{1,16})[：:]", para)
            if not m:
                continue
            speaker = self._speaker_label_base_name(m.group(1))
            if not speaker or speaker == "旁白":
                continue
            total_dialogue += 1
            if speaker in {"霏霏", "樂樂"}:
                sibling_dialogue += 1
        return {
            "pre_incident_dialogue_hits": min(total_dialogue, 199),
            "sibling_banter_hits": min(sibling_dialogue, 199),
        }

    def _damage_risk_hits(self, nodes: Dict[str, Any]) -> int:
        blob = "\n".join(
            [
                self._node_narration(nodes, self.incident_node_id),
                self._node_narration(nodes, "scene_03_check_1"),
                self._node_narration(nodes, "scene_04_check_2"),
                self._node_narration(nodes, "scene_05_check_3"),
                self._node_narration(nodes, "scene_06_hypothesis_1"),
                self._node_narration(nodes, "scene_10_ending_clear"),
                self._node_narration(nodes, "scene_10_ending_nudge"),
                self._node_narration(nodes, "scene_10_ending_defer"),
            ]
        )
        marks = [
            "受傷",
            "擦傷",
            "撞到",
            "絆倒",
            "摔倒",
            "滑倒",
            "燙到",
            "燙傷",
            "打翻",
            "砸到",
            "壞掉",
            "裂開",
            "斷掉",
            "冒煙",
            "設備",
            "道具",
            "線路",
            "推車",
            "玻璃",
            "暫停流程",
            "停擺",
            "宣布暫停",
        ]
        return min(sum(blob.count(mark) for mark in marks if mark in blob), 199)

    def _premature_certainty_hits(self, text: str) -> List[str]:
        t = text or ""
        patterns = [
            "一定是",
            "就是你",
            "就是他",
            "就是她",
            "果然是",
            "原來是你",
            "原來是他",
            "原來是她",
            "看來就是",
            "肯定是",
            "八成是",
        ]
        return [p for p in patterns if p in t]

    # ============================================================
    # Quality report / gate（只產生報告，不改寫內容）
    # ============================================================

    def clue_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        blob = self.collect_narration_text(nodes)
        paras = [x.strip() for x in (blob or "").split("\n\n") if x.strip()]
        public_marks = [
            "舞台",
            "攤位",
            "報到",
            "服務台",
            "廣播",
            "隊伍",
            "後台",
            "表演",
            "比賽",
            "觀眾",
            "來賓",
            "評審",
            "抽獎",
            "關卡",
            "排隊",
            "主持",
            "工作人員",
        ]
        twist_marks = [
            "可是",
            "但是",
            "明明",
            "不是我",
            "我沒有",
            "等一下",
            "先別",
            "剛剛",
            "原來",
            "其實",
            "改口",
            "不敢",
            "怕被",
            "硬說",
        ]
        default_speakers = {"旁白", "霏霏", "樂樂"}
        side_speakers: set[str] = set()
        public_hits = 0
        twist_hits = 0

        for p in paras:
            m = re.match(r"^([^：:\n]{1,12})[：:]", p)
            if m:
                speaker = self._speaker_label_base_name(m.group(1))
                if speaker and speaker not in default_speakers:
                    side_speakers.add(speaker)

            public_hits += sum(1 for w in public_marks if w in p)
            twist_hits += sum(1 for w in twist_marks if w in p)

        # ✅ 事件後自然探索 scene：只算 incident 後面的 nodes（排除 final/ending/quit）
        excluded = {
            "scene_01_start",
            "scene_01_warmup_2",
            "scene_01_warmup_3",
            "final_accuse",
            "scene_10_ending_clear",
            "scene_10_ending_nudge",
            "scene_10_ending_defer",
            "quit",
        }

        ordered = list((nodes or {}).keys())
        inc_idx = ordered.index(self.incident_node_id) if self.incident_node_id in ordered else -1

        post_scene_nodes: list[str] = []
        if inc_idx >= 0:
            for nid in ordered[inc_idx + 1 :]:
                if nid in excluded:
                    continue
                post_scene_nodes.append(nid)

        wrongdoing = self._wrongdoing_scale_report(blob)
        stakes = self._stakes_scale_report(nodes)
        cast_intro_issues = self._first_appearance_grounding_issues(nodes)
        pre_incident_dialogue = self._pre_incident_dialogue_hits(nodes)
        memorable_names = self._memorable_name_style_hits(nodes)
        investigation_blob = "\n".join(
            [
                self._node_narration(nodes, self.incident_node_id),
                self._node_narration(nodes, "scene_03_check_1"),
                self._node_narration(nodes, "scene_04_check_2"),
                self._node_narration(nodes, "scene_05_check_3"),
                self._node_narration(nodes, "scene_06_hypothesis_1"),
            ]
        )
        return {
            "side_speaker_count": len(side_speakers),
            "public_pressure_hits": min(public_hits, 199),
            "twist_hits": min(twist_hits, 199),
            "scene_nodes_count": len(post_scene_nodes),  # ✅ now truly "after incident"
            "sneaky_wrongdoing_hits": int(wrongdoing.get("sneaky_wrongdoing_hits") or 0),
            "accident_softener_hits": int(wrongdoing.get("accident_softener_hits") or 0),
            "ambiguity_hits": self._ambiguity_hits(investigation_blob),
            "cast_grounding_hits": self._cast_grounding_hits(self.pre_incident_text(nodes)),
            "cast_intro_issue_count": len(cast_intro_issues),
            "bigger_consequence_hits": int(stakes.get("bigger_consequence_hits") or 0),
            "adult_takeover_hits": int(stakes.get("adult_takeover_hits") or 0),
            "late_flip_hits": self._late_flip_hits(nodes),
            "pre_incident_dialogue_hits": int(pre_incident_dialogue.get("pre_incident_dialogue_hits") or 0),
            "sibling_banter_hits": int(pre_incident_dialogue.get("sibling_banter_hits") or 0),
            "damage_risk_hits": self._damage_risk_hits(nodes),
            "memorable_name_hits": len(memorable_names),
            "queue_dispute_hits": self._queue_dispute_hits(nodes),
        }

    def style_quality_report(self, nodes: Dict[str, Any]) -> Dict[str, Any]:
        blob = self.collect_narration_text(nodes)

        second_person_hits = 0
        for p in self.gamey_patterns or []:
            if p in blob:
                second_person_hits += blob.count(p)

        # ✅ 教學式「幫你整理/記住重點」命中
        reader_hint_hits = 0
        for p in self.banned_reader_hint_patterns or []:
            if p in blob:
                reader_hint_hits += blob.count(p)

        generic_prose_hits = 0
        for p in self.banned_generic_prose_patterns or []:
            if p in blob:
                generic_prose_hits += blob.count(p)
        for pat in self.generic_prose_regex_patterns or []:
            try:
                generic_prose_hits += len(re.findall(pat, blob))
            except re.error:
                continue

        paras = [x.strip() for x in blob.split("\n\n") if x.strip()]
        seen: set[str] = set()
        dup = 0
        for p in paras:
            key = re.sub(r"\s", "", p)
            if len(key) < 12:
                continue
            if key in seen:
                dup += 1
            else:
                seen.add(key)

        return {
            "second_person_hits": second_person_hits,
            "reader_hint_hits": reader_hint_hits,
            "generic_prose_hits": generic_prose_hits,
            "dup_paragraphs": dup,
        }

    def needs_enrich(self, *, nodes: Dict[str, Any]) -> bool:
        if self.opening_paragraphs(nodes) < self.opening_min_paragraphs:
            return True

        clue = self.clue_quality_report(nodes)
        style = self.style_quality_report(nodes)

        if int(clue.get("scene_nodes_count") or 0) < self.min_scene_nodes_after_required:
            return True
        if int(style.get("second_person_hits") or 0) >= 1:
            return True
        if int(style.get("reader_hint_hits") or 0) >= 1:
            return True
        if int(style.get("generic_prose_hits") or 0) >= 1:
            return True
        if int(style.get("dup_paragraphs") or 0) > 2:
            return True

        rep = self.enrich_report(nodes=nodes, theme="(n/a)")
        if rep.get("reasons"):
            return True

        return False

    # ============================================================
    # Enrich gate (report only)
    # ============================================================

    def _has_kana(self, s: str) -> bool:
        return re.search(r"[\u3040-\u30ff]", s or "") is not None

    def _scene01_text(self, nodes: Dict[str, Any]) -> str:
        s1 = nodes.get("scene_01_start")
        if isinstance(s1, dict):
            return str(s1.get("narration") or "")
        return ""

    def _all_text(self, nodes: Dict[str, Any]) -> str:
        return self.collect_narration_text(nodes)

    def _final_accuse_choices(self, nodes: Dict[str, Any]) -> List[str]:
        fa = nodes.get("final_accuse")
        if not isinstance(fa, dict):
            return []
        ch = fa.get("choices")
        if not isinstance(ch, list):
            return []
        out: List[str] = []
        for it in ch:
            if isinstance(it, dict):
                out.append(str(it.get("text") or "").strip())
        return out

    def _pre_accuse_text_blob(self, nodes: Dict[str, Any]) -> str:
        excluded = {
            "final_accuse",
            "scene_10_ending_clear",
            "scene_10_ending_nudge",
            "scene_10_ending_defer",
            "quit",
        }
        parts: List[str] = []
        for nid, node in (nodes or {}).items():
            if nid in excluded:
                continue
            if isinstance(node, dict):
                nar = node.get("narration")
                if isinstance(nar, str) and nar.strip():
                    parts.append(nar)
        return "\n".join(parts)

    def _node_narration(self, nodes: Dict[str, Any], nid: str) -> str:
        node = (nodes or {}).get(nid)
        if isinstance(node, dict):
            nar = node.get("narration")
            if isinstance(nar, str):
                return nar
        return ""

    def _normalize_name_like(self, text: str) -> str:
        return re.sub(r"[\s　的]", "", text or "")

    def _blob_mentions_name(self, blob: str, name: str) -> bool:
        norm_name = self._normalize_name_like(name)
        norm_blob = self._normalize_name_like(blob)
        return bool(norm_name) and (norm_name in norm_blob)

    def _ordered_node_ids(self, nodes: Dict[str, Any]) -> List[str]:
        return list((nodes or {}).keys())

    def _find_first_incident_node(self, nodes: Dict[str, Any]) -> Optional[str]:
        if self.incident_node_id in (nodes or {}):
            return self.incident_node_id
        return None

    def _count_total_paragraphs(self, nodes: Dict[str, Any]) -> int:
        total = 0
        for nid in self._ordered_node_ids(nodes):
            nar = self._node_narration(nodes, nid)
            if nar:
                total += len(self.split_paragraphs(nar))
        return total

    def _count_paragraphs_before_node(self, nodes: Dict[str, Any], until_nid: str) -> int:
        total = 0
        for nid in self._ordered_node_ids(nodes):
            if nid == until_nid:
                break
            nar = self._node_narration(nodes, nid)
            if nar:
                total += len(self.split_paragraphs(nar))
        return total

    def _ending_ok(self, text: str) -> bool:
        t = text or ""
        has_reason = any(k in t for k in ["因為", "所以", "原來", "其實是", "其實"])
        has_apology = any(k in t for k in ["對不起", "道歉", "抱歉"])
        has_followup = any(
            k in t
            for k in ["下次", "以後", "記得", "提醒", "先說", "先問", "先找", "一起處理", "別自己", "不要自己"]
        )
        paras = len(self.split_paragraphs(t))
        return has_reason and has_apology and has_followup and paras >= self.ending_min_paragraphs

    def _incident_problem_hits(self, text: str) -> List[str]:
        markers = [
            "怎麼",
            "誰",
            "明明",
            "剛剛",
            "不見",
            "找不到",
            "少了",
            "沒有",
            "不是我",
            "為什麼",
            "哪裡",
            "急",
            "慌",
            "糟了",
            "完了",
            "吵",
            "哭",
            "借",
            "還",
            "卡住",
            "順序",
            "輪到",
            "改口",
            "誤會",
            "先別",
            "等一下",
            "不敢",
            "怕被",
            "來不及",
            "上台",
            "報到",
            "評分",
            "被笑",
            "丟臉",
        ]
        return [m for m in markers if m in (text or "")]

    def _incident_flat_hits(self, text: str) -> List[str]:
        hits = [p for p in (self.incident_flat_resolution_patterns or []) if p in (text or "")]
        if (
            "太好了" in (text or "")
            and "找到" in (text or "")
            and not self._incident_problem_hits(text)
        ):
            hits.append("太好了+找到")
        return hits

    def enrich_fail_reasons(self, *, nodes: Dict[str, Any], theme: str) -> List[str]:
        reasons: List[str] = []

        s01 = self._scene01_text(nodes)
        if not s01.strip():
            reasons.append("scene_01_start narration 為空")
            return reasons

        open_paras = len(self.split_paragraphs(s01))
        if open_paras < self.opening_min_paragraphs:
            reasons.append(f"scene_01_start 段落不足（{open_paras} < {self.opening_min_paragraphs}）")
        pre_incident_paras = self.pre_incident_paragraphs(nodes)
        if pre_incident_paras < self.pre_incident_min_paragraphs:
            reasons.append(
                f"前段鋪墊太短（scene_01_start + warmup 共 {pre_incident_paras} 段，至少希望有 {self.pre_incident_min_paragraphs} 段）"
            )

        # ✅ scene_01_start 禁詞
        open_hits = self._has_any_opening_banned(s01)
        if open_hits:
            reasons.append(f"scene_01_start 出現開場禁詞（包含轉述/台詞/引號）：{open_hits}")

        opening_overview_hits = self._opening_overview_hits(s01)
        if opening_overview_hits:
            reasons.append(f"scene_01_start 首段太像總覽口播：{opening_overview_hits[:3]}")
        if not self._opening_person_action_ok(s01):
            reasons.append("scene_01_start 第一段還沒有先讓人出現（最好一進來就看到某個人在忙、衝、找人或出糗）")

        arrival_hits = self._opening_arrival_context_hits(s01)
        if not arrival_hits:
            reasons.append("scene_01_start 缺少到場理由/同行關係（讀者還不知道為什麼來這裡）")

        if self._has_kana(s01):
            reasons.append("scene_01_start 出現日文假名（平假名/片假名）")

        gen_hits = [w for w in (self.banned_generics or []) if w in s01]
        if gen_hits:
            reasons.append(f"scene_01_start 出現泛稱（請改成有名字的配角）：{gen_hits}")

        blob_all = self._all_text(nodes)

        ph_hits = self._placeholder_like_hits(blob_all)
        if ph_hits:
            reasons.append(f"出現 placeholder/佔位命名：{ph_hits[:3]}")

        generic_speaker_hits = self._generic_speaker_label_hits(blob_all)
        if generic_speaker_hits:
            reasons.append(
                f"配角稱呼太泛，請改成自然名字或關係稱呼：{generic_speaker_hits[:4]}"
            )

        pn_hits = [w for w in (self.banned_proper_nouns or []) if w in blob_all]
        if pn_hits:
            reasons.append(f"出現其他案例殘影/專有名詞：{pn_hits[:4]}")

        gamey_hits = [p for p in (self.gamey_patterns or []) if p in blob_all]
        if gamey_hits:
            reasons.append(f"出現對讀者下指令/遊戲提示句型：{gamey_hits[:4]}")

        # ✅ 全篇禁：幫讀者整理/記重點/排除
        hint_hits = [p for p in (self.banned_reader_hint_patterns or []) if p in blob_all]
        if hint_hits:
            reasons.append(f"出現『幫讀者整理/記重點/排除』句型：{hint_hits[:5]}")

        generic_hits = [p for p in (self.banned_generic_prose_patterns or []) if p in blob_all]
        for pat in self.generic_prose_regex_patterns or []:
            try:
                if re.search(pat, blob_all):
                    generic_hits.append(f"regex:{pat}")
            except re.error:
                continue
        if generic_hits:
            reasons.append(f"出現空泛 AI 說書套句：{generic_hits[:5]}")

        admission_gaps = self._ungrounded_admission_paras(blob_all)
        if admission_gaps:
            reasons.append(f"前因交代太跳：角色自責/補述前沒有先講清楚剛剛做了什麼：{admission_gaps[:2]}")

        # ✅ 案件存在 gate
        if self.incident_node_id not in (nodes or {}):
            reasons.append(f"缺少案件節點：必須包含 {self.incident_node_id}")
        else:
            inc_text = self._node_narration(nodes, self.incident_node_id)
            if not inc_text.strip():
                reasons.append(f"{self.incident_node_id} narration 為空")
            else:
                incident_problem_hits = self._incident_problem_hits(inc_text)
                incident_flat_hits = self._incident_flat_hits(inc_text)
                if incident_flat_hits:
                    reasons.append(f"{self.incident_node_id} 太像把麻煩自己收掉：{incident_flat_hits[:4]}")
                elif not incident_problem_hits:
                    reasons.append(f"{self.incident_node_id} 缺少明確要查清楚的麻煩")

        # final_accuse gate
        choices = self._final_accuse_choices(nodes)
        if not choices:
            reasons.append("final_accuse choices 缺失或格式不正確")
        else:
            if len(choices) != 4:
                reasons.append(f"final_accuse choices 必須剛好 4 個（目前 {len(choices)}）")
            else:
                if (choices[3] or "").strip() != self.unsure_choice_text.strip():
                    reasons.append(f"final_accuse 第 4 個選項必須完全等於：{self.unsure_choice_text}")

                suspects = [choices[0].strip(), choices[1].strip(), choices[2].strip()]
                if len(set(suspects)) != 3:
                    reasons.append(f"嫌疑人名字重複：{suspects}")

                pre_blob = self._pre_accuse_text_blob(nodes)
                for s in suspects:
                    if self._name_is_too_generic_or_placeholder(s):
                        reasons.append(f"嫌疑人名字太泛或像 placeholder：{s}")
                    elif s and (not self._blob_mentions_name(pre_blob, s)):
                        reasons.append(f"嫌疑人未在指認前登場：{s}")

                fa = nodes.get("final_accuse")
                if isinstance(fa, dict):
                    si = fa.get("solution_index", None)
                    try:
                        si_int = int(si)
                    except Exception:
                        si_int = None
                    if si_int not in (0, 1, 2):
                        reasons.append(f"final_accuse.solution_index 必須是 0/1/2（目前：{si}）")

        # ✅ final_accuse narration 禁止「列舉嫌疑人/幫玩家整理」
        fa = nodes.get("final_accuse")
        if isinstance(fa, dict):
            fa_nar = str(fa.get("narration") or "")
            # 嫌疑人名字來自 choices[0..2]
            choices2 = self._final_accuse_choices(nodes)
            suspects2: list[str] = []
            if len(choices2) >= 3:
                suspects2 = [choices2[0].strip(), choices2[1].strip(), choices2[2].strip()]

            # (A) narration 內出現任何嫌疑人名字 → fail
            named_hits = [s for s in suspects2 if s and self._blob_mentions_name(fa_nar, s)]
            if named_hits:
                reasons.append(f"final_accuse narration 不得提到嫌疑人名字（命中：{named_hits}）")

            # (B) narration 出現「列舉/整理口吻」→ fail
            # ✅ 修正：避免把「最後時刻/最後一段」誤判成列舉
            # 只抓真的像在列舉（第一個/第二個/第三個/最後 +（一個/位/名/條/個/：））
            enum_regexes = [
                r"(第[一二三]個)\s*([一位名條個]|：|:)",
                r"(最後)\s*([一位名條個]|：|:)",
                r"(還有|另外|以及|再來)\s*([一位名條個]|：|:)",
                r"(可能是)\s*([一位名條個]|：|:)",
            ]
            enum_hits = []
            for pat in enum_regexes:
                if re.search(pat, fa_nar):
                    enum_hits.append(pat)
            if enum_hits:
                reasons.append(
                    "final_accuse narration 出現列舉/整理口吻（regex 命中）"
                )

            accuse_tone_hits = [p for p in (self.banned_accuse_tone_patterns or []) if p in fa_nar]
            if accuse_tone_hits:
                reasons.append(f"final_accuse narration 語氣太像逼問/審訊：{accuse_tone_hits[:4]}")

        # 事件後搜尋 scene 數
        clue = self.clue_quality_report(nodes)
        cast_intro_issues = self._first_appearance_grounding_issues(nodes)
        if int(clue.get("side_speaker_count") or 0) < 4:
            reasons.append(
                f"配角存在感不足（具名配角/關係稱呼太少：{int(clue.get('side_speaker_count') or 0)}）"
            )
        if (
            int(clue.get("side_speaker_count") or 0) >= 4
            and int(clue.get("cast_grounding_hits") or 0) < 4
        ):
            reasons.append(
                "配角關係交代不足（讀者還不夠知道這些人是誰、為什麼跟主角一起出現在這裡）"
            )
        if cast_intro_issues:
            reasons.append(
                f"配角第一次出場太跳（這些名字初登場時沒有順手交代關係/職責：{cast_intro_issues[:4]}）"
            )
        if (
            int(clue.get("side_speaker_count") or 0) >= 3
            and int(clue.get("memorable_name_hits") or 0) < 1
        ):
            reasons.append("配角名字記憶點偏弱（至少留一兩個像「鉛筆小白 / 狐狸小右 / 廣播阿姨阿秀」這種一聽就記得住的名字）")
        if int(clue.get("pre_incident_dialogue_hits") or 0) < 10:
            reasons.append(
                f"前段互動太少（事件前真正的對話/打鬧還不夠：{int(clue.get('pre_incident_dialogue_hits') or 0)}）"
            )
        if int(clue.get("sibling_banter_hits") or 0) < 4:
            reasons.append(
                f"霏霏樂樂前段打鬧感不足（事件前姊弟互動太少：{int(clue.get('sibling_banter_hits') or 0)}）"
            )
        if int(clue.get("twist_hits") or 0) < 6:
            reasons.append(
                f"誤導層次偏弱（說法互撞/改口/遮掩太少：{int(clue.get('twist_hits') or 0)}）"
            )
        if int(clue.get("late_flip_hits") or 0) < 3:
            reasons.append(
                f"後段翻盤不夠狠（scene_05/06 還不夠像『差點又信了另一邊』：{int(clue.get('late_flip_hits') or 0)}）"
            )
        if (
            int(clue.get("sneaky_wrongdoing_hits") or 0) < 3
            and int(clue.get("accident_softener_hits") or 0) >= 4
        ):
            reasons.append(
                "案件太像純忙中出錯/小誤會（故意亂動、偷偷藏、偷改、搶風頭的力道太弱）"
            )
        if int(clue.get("bigger_consequence_hits") or 0) < 2:
            reasons.append("案件後果太輕（還像小小惡作劇，沒有長成差點釀成更大麻煩的感覺）")
        if int(clue.get("damage_risk_hits") or 0) < 2:
            reasons.append("事件真實衝擊太弱（還沒有明顯碰到受傷風險、設備受損或流程停擺的邊緣）")
        if (
            int(clue.get("queue_dispute_hits") or 0) >= 6
            and int(clue.get("sneaky_wrongdoing_hits") or 0) < 5
        ):
            reasons.append("核心麻煩又縮成排隊/順位糾紛（除非背後還連著更大的破壞、危險或偷動手腳，否則不要只靠插隊換位撐整案）")
        if (
            int(clue.get("bigger_consequence_hits") or 0) >= 2
            and int(clue.get("adult_takeover_hits") or 0) < 1
        ):
            reasons.append("結尾缺少大人接手收場（事情差點鬧大了，卻沒看到大人把現場穩住）")
        if int(clue.get("ambiguity_hits") or 0) < 4:
            reasons.append(
                f"調查太快變清楚（模糊但有方向的句子太少：{int(clue.get('ambiguity_hits') or 0)}）"
            )
        if int(clue.get("scene_nodes_count") or 0) < self.min_scene_nodes_after_required:
            reasons.append(
                f"事件後搜尋/互動 scene 不足（{int(clue.get('scene_nodes_count') or 0)} < {self.min_scene_nodes_after_required}）"
            )

        for nid in ("scene_05_check_3", "scene_06_hypothesis_1"):
            certainty_hits = self._premature_certainty_hits(self._node_narration(nodes, nid))
            if certainty_hits:
                reasons.append(f"{nid} 太快定調嫌疑人（命中：{certainty_hits[:3]}）")

        # endings
        for eid in ("scene_10_ending_clear", "scene_10_ending_nudge", "scene_10_ending_defer"):
            nar = self._node_narration(nodes, eid)
            if not nar.strip():
                reasons.append(f"{eid} narration 為空")
                continue
            if not self._ending_ok(nar):
                reasons.append(f"{eid} 結尾不完整：必須包含『原因道歉後續收束』且至少 {self.ending_min_paragraphs} 段")
            moral_hits = self._ending_moralizing_hits(nar)
            if moral_hits:
                reasons.append(f"{eid} 收尾太像品德摘要：{moral_hits[:4]}")

        if len(choices) >= 3:
            suspects = [choices[0].strip(), choices[1].strip(), choices[2].strip()]
            ending_name_map: Dict[str, str] = {}
            for eid in ("scene_10_ending_clear", "scene_10_ending_nudge", "scene_10_ending_defer"):
                nar = self._node_narration(nodes, eid)
                hits = [s for s in suspects if s and self._blob_mentions_name(nar, s)]
                if len(hits) == 1:
                    ending_name_map[eid] = hits[0]
            if len(set(ending_name_map.values())) > 1:
                reasons.append(f"三個 endings 提到的嫌疑人不一致：{ending_name_map}")

        return reasons

    def enrich_report(self, *, nodes: Dict[str, Any], theme: str) -> Dict[str, Any]:
        rep = {
            "theme": theme,
            "opening_paragraphs": self.opening_paragraphs(nodes),
            "clue": self.clue_quality_report(nodes),
            "style": self.style_quality_report(nodes),
        }
        rep["reasons"] = self.enrich_fail_reasons(nodes=nodes, theme=theme)
        return rep

    # ============================================================
    # Meta
    # ============================================================

    def ensure_case_id(self, meta: Dict[str, Any], forced_case_id: str | None) -> None:
        if forced_case_id:
            meta["case_id"] = forced_case_id
            return
        if not str(meta.get("case_id") or "").strip():
            meta["case_id"] = f"ai_{uuid.uuid4().hex[:10]}"

    # ============================================================
    # Prompt builders
    # ============================================================

    def json_skeleton(self) -> str:
        # ✅ 骨架：加入 warmup 節點，避免 scene_01_start 一口氣跳到 incident
        # ✅ 避免模型在 final_accuse 幫玩家整理嫌疑人
        return f"""
請只輸出 JSON（不要 markdown、不要 code fence、不要解釋）。
最外層只能有 meta, nodes。

{{
  "meta": {{
    "schema_version": "v1",
    "title": "故事標題",
    "tags": ["ai"]
  }},
  "nodes": {{
    "scene_01_start": {{
      "title": "開場節點標題（可自訂）",
      "narration": "至少 {self.opening_min_paragraphs} 段；用 \\n\\n 分段；前半要更像一整段生活現場：今天到底是什麼活動、現場有哪些區域/比賽/流程、霏霏和樂樂為什麼會來、今天被分到什麼、至少兩三輪姊弟打鬧和配角互動；但不要只有導覽詞，馬上要落回具體人和正在發生的事",
      "choices": [{{"text":"繼續","next":"scene_01_warmup_2"}}]
    }},
    "scene_01_warmup_2": {{
      "title": "warmup 節點標題（可自訂）",
      "narration": "延續同一場景；讓人物互相擦撞、逞強、嘴硬、搶快、幫倒忙、亂傳話都可以；玩笑要自然，不要像作者硬加進來；多補一點任務、分工、排隊、東西香味、誰在忙誰在喘；先不要把案件講破",
      "choices": [{{"text":"再繼續","next":"scene_01_warmup_3"}}]
    }},
    "scene_01_warmup_3": {{
      "title": "warmup 節點標題（可自訂）",
      "narration": "把注意力慢慢拉向即將出事的區域、人群或說法；讓大家覺得哪裡開始不對勁，但不要一下就把答案講完",
      "choices": [{{"text":"我們去看看","next":"{self.incident_node_id}"}}]
    }},
    "{self.incident_node_id}": {{
      "title": "事件節點標題（可自訂）",
      "narration": "案件發生：用自然方式描述今天冒出一件真的會讓場面卡住、讓人難堪、把大家判斷帶歪，甚至差點害人受傷、差點弄壞設備或道具、差點讓流程被迫喊停的事；更像樣本的是有人故意亂動、偷偷破壞、偷改、安全動線被搞亂、搶風頭害人出糗；最後仍由大人穩住現場，不要寫成嚇人的重刑場面",
      "choices": [{{"text":"一起看看發生什麼事","next":"scene_03_check_1"}}]
    }},
    "scene_03_check_1": {{
      "title": "check 節點標題（可自訂）",
      "narration": "先去看一個人、一個區域、或一個說法；重點是把懷疑往一個方向推，但不要太快蓋棺定論",
      "choices": [{{"text":"再找找看","next":"scene_04_check_2"}}]
    }},
    "scene_04_check_2": {{
      "title": "check 節點標題（可自訂）",
      "narration": "換另一個角度、另一個區域、或另一個人的說法；讓前面的懷疑開始動搖，最好帶出人情或面子壓力",
      "choices": [{{"text":"換個地方看看","next":"scene_05_check_3"}}]
    }},
    "scene_05_check_3": {{
      "title": "check 節點標題（可自訂）",
      "narration": "把更深一層的不對勁翻出來：時間差、說法矛盾、人情壓力、誰在遮什麼、或誰其實在幫別人擋；最好在這裡做出第二層以上翻轉",
      "choices": [{{"text":"我有一個猜想","next":"scene_06_hypothesis_1"}}]
    }},
    "scene_06_hypothesis_1": {{
      "title": "hypothesis 節點標題（可自訂）",
      "narration": "讓角色開始拼圖，但只能說不完整的猜想；霏霏把焦點拉回真正卡住的地方，但不要列點整理；樂樂可以先亂猜再被接回來",
      "choices": [{{"text":"我要指認","next":"final_accuse"}}]
    }},
    "final_accuse": {{
      "title": "誰可能和這件事有關呢？",
      "narration": "只能是短導語（2~4 段）：提醒要選了 + 自然接住當下氣氛 + 告訴孩子也可以選『{self.unsure_choice_text}』；❌ 禁止列舉嫌疑人名字與理由；❌ 禁止回顧線索",
      "choices": [
        {{"text":"嫌疑人1","next":"scene_10_ending_clear"}},
        {{"text":"嫌疑人2","next":"scene_10_ending_nudge"}},
        {{"text":"嫌疑人3","next":"scene_10_ending_defer"}},
        {{"text":"{self.unsure_choice_text}","next":"scene_10_ending_defer"}}
      ],
      "solution_index": 0
    }},
    "scene_10_ending_clear": {{
      "title": "結尾（推理正確）",
      "narration": "...（真相/情緒/道歉/收尾；至少 {self.ending_min_paragraphs} 段；可以有大人接手，把人帶去了解、安撫、說明或請家長老師處理，但不要變訓話或嚇人威脅）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "scene_10_ending_nudge": {{
      "title": "結尾（差一點）",
      "narration": "...（真相/情緒/道歉/收尾；至少 {self.ending_min_paragraphs} 段；可以有大人接手，把人帶去了解、安撫、說明或請家長老師處理，但不要變訓話或嚇人威脅）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "scene_10_ending_defer": {{
      "title": "結尾（交給大人）",
      "narration": "...（真相/情緒/道歉/收尾；至少 {self.ending_min_paragraphs} 段；包含『不確定也沒關係』的收束；大人可接手帶去了解，但不要寫成可怕懲罰）",
      "choices": [{{"text":"故事結束","next":"quit"}}]
    }},
    "quit": {{
      "title": "結束",
      "narration": "旁白：故事先到這裡，謝謝你一起當小偵探！",
      "choices": [],
      "can_replay": true,
      "can_quit": true
    }}
  }}
}}
""".strip()

    def build_user_prompt(
        self,
        *,
        rules_text: str,
        seed: Optional[int],
        nonce: str,
        theme: str,
        include_old_rival: bool,
    ) -> str:
        instructions = self.build_instructions(include_old_rival=include_old_rival)
        seed_key = f"{int(seed)}" if seed is not None else "null"
        style_opening = extract_style_example(
            max_lines=28,
            selector=f"{seed_key}:{nonce}:opening",
            focus="opening_event",
        )
        style_case = extract_style_example(
            max_lines=22,
            selector=f"{seed_key}:{nonce}:twist",
            focus="human_twist",
        )
        engine = self.pick_story_engine(seed, nonce)
        incident_shape = self.pick_incident_shape(seed, nonce)
        seed_line = f"{int(seed)}" if seed is not None else "null"
        grounding_hint = self.theme_grounding_hint(theme)

        opening_banned_all = self._opening_banned_all()
        reader_hint_banned = self.banned_reader_hint_patterns or []
        generic_prose_banned = self.banned_generic_prose_patterns or []

        # 結尾關鍵字（硬性要求，對齊 _ending_ok 的 gate）
        ending_reason_kw = "因為/所以/原來/其實是"
        ending_apology_kw = "對不起/抱歉/道歉"
        ending_teach_kw = "下次/以後/記得/提醒/先說/先問"

        engine_block = ""
        if engine:
            engine_block = f"""
【本輪故事引擎（學方向，不要照抄）】
- 這次的故事引擎：{engine.get("name", "")}
- 開場感：{engine.get("setup", "")}
- 場面壓力：{engine.get("pressure", "")}
- 誤導方式：{engine.get("mislead", "")}
- 真相的人味：{engine.get("human_core", "")}
""".strip()

        incident_block = ""
        if incident_shape:
            incident_block = f"""
【本輪事件形狀（學方向，不要照抄）】
- 事件偏好：{incident_shape.get("name", "")}
- 這類事件通常長這樣：{incident_shape.get("shape", "")}
- 防偷懶提醒：{incident_shape.get("drift_guard", "")}
""".strip()

        prompt = f"""
{rules_text}

{instructions}

你是一位「故事型偵探推理遊戲」的兒童故事作家，要寫給小一能懂、好笑、有日常感（霏霏＆樂樂）。

【先抓樣本手感，不要抓模板】
- 先把場子寫活，再讓事件長出來。scene_01_start 與 warmup 不只是過場，而是要讓這個活動像一整集真的正在運轉。
- 背景要有大場面感，不要只剩一個角落。最好讓讀者能看見至少幾個正在動的區域，例如舞台、報到桌、攤位、服務台、後台、排隊區、休息區。
- 開場第一句就要有戲。你可以先用 1~2 段交代「今天是一年一度的什麼活動、這裡到底在辦什麼」，但那兩段必須帶活動名字、現場區域、比賽/流程內容，不能只有空拍總覽；接著馬上要落到一個具體人、一句話、一個狼狽動作或一個卡住的場面。
- 第一個畫面最好直接先看見某個人正在忙、衝、扛、擦汗、找人、拌嘴或出糗，再順手知道今天到底在辦什麼；不要讓第一句完整停在「一年一度的什麼活動今天開始了」。
- 第一段盡量不要只用「今天這裡正在舉辦……」起手。更像樣本的是：先看到某個人正在忙、衝、喊、擦汗、搶話、出糗，再在同一段裡順手帶出今天到底在辦什麼。
- 開場前 3 到 5 段也要自然交代霏霏和樂樂為什麼今天會在這裡、跟誰來、原本是來玩/來住/來參加什麼、今天被分到什麼或想先衝哪一區，不要像鏡頭一開他們就已經憑空站在場中央。
- 前半可以更有溫度、更久一點。scene_01_start 加上兩個 warmup，通常應該長到像故事前半集：先讓讀者認識人、喜歡場子、記住誰在搶話誰在鬧、知道今天各自負責什麼，然後才真的出事，不要一兩個轉身就直接進案子。
- 在真正出事前，最好先有 2 到 3 輪姊弟打鬧、配角插話、現場任務或小狼狽，讓孩子真的逛進這個場合。
- 開頭先讓配角有記憶點。不要只有「有幾個同學」，而是要有會搶話的人、愛逞強的人、忙到快飛起來的人、嘴硬的人；而且最好第一次開口就帶出毛病。
- 配角名字最好留一兩個一聽就記得住的名字。孩子角色可以偏可愛綽號式或外號式，例如「鉛筆小白 / 狐狸小右 / 糖果小莓」；大人也可以用「職責/關係 + 暱稱」，例如「廣播阿姨阿秀 / 點心叔叔阿發」。
- 配角第一次出場時，順手交代他是誰、跟主角或活動的關係、為什麼會跟大家站在一起。最好直接寫成「關係/職責 + 名字 + 當下在做什麼」的樣子，例如「霏霏的同學阿棠正抱著號碼牌喘氣」；不要只丟一串名字，讓讀者自己猜這些人是不是路人。
- final_accuse 前那三個嫌疑人，不能像突然路過的名字。前半就要先讓讀者知道：他是誰、為什麼會在現場、跟主角靠近在哪個區域、剛剛在忙什麼。
- 案件不要老是退回「一個普通東西不見了」。可以有失物，但更像樣本的是：流程卡住、話被講歪、有人遮難堪、有人假會、有人替別人擋、有人快被全場誤會。
- 不要把每件事都洗成小失誤或好心辦壞事。這次更常要像樣本那樣，真的有某個孩子或年紀小的人故意亂動、偷偷藏、偷改、搶風頭、卡別人、害人出糗；尺度仍然是兒童故事，但可以有明確的小壞心眼。
- 惡作劇可以只是想鬧一下，但後果可以比做壞事的人原本想得更嚴重，例如差點讓人受傷、差點打翻熱東西、差點扯倒道具、差點撞壞設備、差點讓舞台或流程被迫喊停。不用真的寫到可怕傷害，但要讓大家意識到這已經不是小玩笑，而是差點要出事。
- 事件不要老是停在「亂喊一聲 / 換一下號碼 / 偷偷藏一張牌」。也請多往「破壞道具、動到設備、安全動線被搞亂、差點害人受傷、差點讓重要東西壞掉」這種更有重量的方向寫。
- 除非「插隊 / 換位 / 順序亂掉」只是表面現象，背後還連著更大的破壞、危險或偷動手腳，否則不要把核心案件縮在排隊糾紛。
- 推進不要只靠撿東西、看痕跡。多用說法互撞、改口、時間差、面子、護短、丟臉、硬撐，做出至少兩層「原本以為是這樣，結果又不是」。
- 誤導要夠狠：至少先讓一個人看起來 70% 像真的做了，再用第二層說法把讀者翻走，不要只是有人被輕輕懷疑一下。
- `scene_05_check_3` 最好不是確認上一輪懷疑，而是再丟出一個差點把讀者翻走的新方向、新目擊、新說法或新動機。
- `scene_06_hypothesis_1` 也不要只剩一條路。至少保留兩個還說得通一半的解釋，讓孩子在指認前還會搖一下。
- `scene_05_check_3` 和 `scene_06_hypothesis_1` 不要直接寫「一定是 / 就是他 / 果然是 / 八成是」這種拍板句。
- 調查不要太快講清楚。每一輪 check 都應該像樣本那樣「有方向，但還不能拍板」；到 final_accuse 前，讀者最好還是有點搖擺，不能太早就知道答案。
- 如果故事裡真的有人動手腳，不要太快把他洗白成「其實只是手滑」；比較像樣本的是他有嫉妒、不爽、報復、想搶表現、想讓別人難看一下這種很孩子氣但確實存在的動機。
- 動機請輪流，不要老是怕丟臉、怕輸、怕被罵。也可以是：報復被笑過、嫉妒別人太受歡迎、想搶注意力、想幫朋友出氣、惡作劇過頭、貪心想多拿、偷懶想把鍋甩給別人。
- 如果有人說「我的疏忽 / 我的錯 / 我剛剛太忙了」，同一段或前一段就要先落地講出他剛剛把什麼貼錯、拿錯、放錯、說錯，不要先丟抽象自責再叫讀者自己補。
- 如果事件已經差點釀成比較大的麻煩，ending 可以讓老師、站務員、家長或工作人員接手，帶人去了解、拉到旁邊說明、安撫被波及的人、通知家長或暫時帶離現場；不用寫成關起來、重罰、嚇人威脅。
- 笑點要像姊弟平常打鬧，不要像作者表演俏皮話。尤其不要出現感官亂接的笑話，例如不是食物卻突然說想咬一口。
- 旁白要具體，不要掉進空泛 AI 套句。以下這些整篇都不要直接寫出來：{", ".join(generic_prose_banned[:8])}
- 開場第一段可以先交代活動名稱與今天的場合，例如「一年一度的什麼活動今天開始了」，但不能只停在導覽口播；最好同一段或下一段就撞到一個正在忙的人、正在出糗的事、或一句讓場子動起來的話。
- 如果場地平常偏安靜，必須自然交代今天為什麼特別熱鬧，不要讓舞台、廣播、群眾像憑空冒出來。
- 場景不只要大，也要像它自己。不要把車站寫成 generic 園遊會、把百貨寫成 generic 操場、把港口寫成 generic 攤位區。

【角色口氣】
- 霏霏：熱心、貼心、愛笑、活潑，愛跟弟弟打鬧開玩笑，但比較理性；她會接住場面，不會一路板著臉講道理。
- 樂樂：愛吃、衝動、很愛鬧姊姊，也愛看姊姊無奈；他的好笑要像真的嘴快、真的想吃、真的亂猜，不是故意講怪話。

【保留相容結構，但不要寫成模板】
- scene_01_start 仍然必須至少 {self.opening_min_paragraphs} 段；開場禁詞現在只擋直接破案/審訊口氣（包含引號、括號、轉述、角色台詞）：{", ".join(opening_banned_all)}
- 必須包含 {self.incident_node_id}、final_accuse、3 個 ending、quit 這些節點；節點 id 與 choices 結構要相容，但 title 可自由命名。
- final_accuse 前 3 個嫌疑人都必須是前面登場過、有名字、而且各自有一個讓人先懷疑的點的人。
- 有台詞的配角和大人，請用自然名字或關係稱呼，例如「林老師 / 樂樂的爸爸 / 廣播阿姨阿秀」；不要寫成「老師A / 爸爸B / 志工2 / 單純的老師」。
- final_accuse 的 narration 只能是短導語，不能列舉嫌疑人名字與理由，不能替玩家整理推理。
- final_accuse 第 4 個選項必須完全等於：{self.unsure_choice_text}
- solution_index 只能 0/1/2
- 結尾三段（clear/nudge/defer）都要完整：原因 + 道歉 + 後續怎麼收/下次怎麼做，且至少 {self.ending_min_paragraphs} 段；三個 endings 必須說同一件事的同一個真相，不要寫成品德摘要。
- 全篇禁止「幫讀者整理線索/重點回顧/請記住/因此排除/結論是…」這種口吻：{", ".join(reader_hint_banned)}
- final_accuse 不是審問現場。霏霏不能突然像檢察官逼問「你是不是」「要不要承認」。

【場景】
- 本次場景建議：{theme if theme else "由你自由決定（安全、日常尺度）"}
- 這只是場景起點，不是固定模板；請自己把這個場合長成一個完整世界。
- 這個場景的落地提醒：{grounding_hint if grounding_hint else "讓地點本身的工作節奏、動線和人群真的成立。"}

{engine_block}

{incident_block}

【指認】
- final_accuse 必須 4 個選項，且第 4 個必須完全等於：{self.unsure_choice_text}
- solution_index 只能 0/1/2

【禁止對讀者下指令】
- 不要出現：{", ".join(self.gamey_patterns or [])}

【輸出格式】
- 只輸出 JSON object（不要 markdown / code fence）
- 最外層只能有 meta, nodes
- narration 用 \\n\\n 分段，每段用「角色：內容」開頭（旁白/霏霏/樂樂/林老師/樂樂的爸爸/廣播阿姨阿秀 等）

{self.json_skeleton()}

【樣本開場錨點（只學節奏/視角，不得照抄）】
{style_opening}

【樣本人味與誤導錨點（只學方向，不得照抄）】
{style_case}

seed={seed_line}
nonce={nonce}

最後提醒：只輸出 JSON object。
成稿前再做最後自查：
- 如果一句旁白把人名和場景換掉後，還能套進任何別的故事，通常代表它太空，請重寫。
- 這個背景是不是像一整集會發生事的大場面，而不是只有一個角落？
- 這個場景是不是像它自己？如果把地名拿掉後，還像 generic 園遊會模板，請重寫得更落地。
- scene_01_start 第一段如果只有活動簡介，卻沒有很快接到具體人物、任務、區域或正在發生的事，請重寫。
- scene_01_start 第一段如果還沒有任何一個人在做事，只剩夜景、燈光、氣氛或活動名稱，也請重寫。
- {self.incident_node_id} 結束時，麻煩有沒有真的還留著，值得往下查？
- 這個案件如果拿掉，現場活動是不是還會照常進行？如果答案是會，通常代表案件太小了。
- 這次是不是又偷懶寫成「某樣東西不見了」？如果是，請再往人物的嘴硬、丟臉、遮掩、搶風頭和誤會多推一步。
- 這次是不是又把本來可以寫成偷偷搞事、搶風頭、故意亂動的事件，洗成普通手滑或小誤會？如果是，請把那股主動的小壞心眼寫回來。
- 有台詞的配角是不是都有自然名字或關係稱呼？如果還有「老師A / 爸爸B / 志工2 / 老師：」這種寫法，請重寫。
- final_accuse 是否像孩子在整理當下狀況，而不是在審人？
- ending 是不是有人真的把場面收住、事情真的落地，而不是最後忽然總結出一個大道理？
- 霏霏和樂樂是不是像會一起打鬧、一起往前衝的姊弟，而不是兩個功能型播報員？
- 三個 endings 的做錯的人、原因、道歉對象，是否前後一致？
"""
        return textwrap.dedent(prompt).strip()

    def build_polish_prompt(self, *, raw_json: str, theme: str) -> str:
        style = extract_style_example(selector=f"polish:{theme}", focus="human_twist")
        return f"""
你是「故事二次潤句編輯」。
你的任務不是重寫故事，而是把一份已經成形的故事 JSON 修成更自然、更順口、更像樣本。

theme={theme}

【你只能做的事】
- 只修文字自然度、邏輯順暢度、玩笑落點、角色口氣
- 可以改：meta.title、各節點 title、各節點 narration
- 不可以改：node id、節點順序、choices 的數量/text/next、solution_index、can_replay、can_quit、case_id、schema_version
- 不可以改案件事實、真相、誰是正解、事件順序

【你要優先修掉的問題】
- 一句話需要停下來想「這是什麼意思」
- 比喻太跳、太刻意、邏輯不通
- 玩笑像作者在抖機靈，不像角色平常會說的話
- 感官亂接的玩笑，例如不是食物卻突然說想咬一口
- 推理句太糊，讀者不知道角色到底在比對哪個不對勁
- 霏霏太像正經小老師，或樂樂太像硬塞笑點機器
- 同一種舊味道句型反覆出現，例如怪怪的、再看一下、亮亮的、黏黏的，但沒有真正推進
- 開場旁白太空，像任何故事都能套用，例如「陽光燦爛的午後」「熱鬧非凡」「忙得不可開交」「充滿某種氣氛」
- 背景看起來只有一個小角落，沒有活動規模、動線、群體壓力
- 開場只知道這裡很熱鬧，卻不知道今天到底是什麼活動、現場有哪些比賽或流程、霏霏樂樂為什麼來這裡
- 前半還沒讓人進入故事、認識人物和場子，事件就太快冒出來
- 事件明明應該麻煩升高，卻被寫成只是看到一個東西、幫一下忙、或當場就沒事
- 案件太小，拿掉之後整個活動還是照常進行
- 又默默滑回「某樣東西不見了」這種最省力案件，但沒有更大的人情或場面壓力
- 案件被寫成單純手忙腳亂、拿錯放錯、小誤會，沒有誰真的偷偷亂動、故意卡人、搶風頭或想讓別人難看
- 調查走得太直，第二輪前後就已經幾乎只剩一個答案，沒有樣本那種模糊兩可的搖擺
- 配角被寫成「老師A / 爸爸B / 志工2 / 老師：」這種太泛或佔位的稱呼
- 開場第一段只有活動簡介或導覽詞，沒有很快落到具體人物與今天任務
- 開場把人直接丟進場地裡，卻沒自然交代今天為什麼會來、跟誰來、原本要做什麼
- 配角第一次出場還不夠鮮，只能靠旁白介紹，沒有一開口就帶出脾氣或毛病
- 陌生名字突然裸出，讀者不知道那個人是誰、跟主角什麼關係、為什麼會跟大家站在一起
- 誤導只是點到一下，沒有真的讓讀者先站錯邊
- 有人突然說「我的疏忽 / 我的錯 / 我剛剛太忙了」，但前一段或同段沒先講清楚他剛剛做了哪個動作
- 壞事後果太小，只像日常小搗蛋，沒有長成差點更嚴重的大麻煩
- 明明事情已經差點鬧大了，ending 卻沒有大人出手把場面接住
- ending 像品德課摘要，例如「大家學到……的重要性」
- final_accuse 太像在逼供，霏霏忽然變成檢察官
- clear / nudge / defer 三個 endings 彼此對不上，做錯的人或原因漂移

【角色提醒】
- 霏霏：熱心、貼心、愛笑、活潑，愛跟弟弟打鬧，但比較理性；像會笑著把場面接住的姊姊
- 樂樂：愛吃、衝動、愛鬧姊姊、愛看姊姊無奈；他的好笑要像真反應，不像刻意賣萌

【成稿前請逐句自查】
- 這句話拿去念給人聽，會不會讓人愣一下？
- 這句玩笑不用解釋也聽得懂嗎？
- 這句推理話有沒有明確指出在比對哪件事？
- 這句話像人物自己會說的，還是像作者硬塞的？
- 有台詞的配角是不是有自然名字或關係稱呼，而不是「老師A / 爸爸B / 老師：」？
- 配角第一次開口時，能不能立刻分出誰愛搶、誰愛現、誰怕丟臉、誰在硬撐？
- 如果拿掉人名與場景，這句旁白還能套進任何故事嗎？如果可以，請改得更具體
- 開場前幾段有沒有自然交代：今天到底是什麼活動、現場有哪幾塊區域/比賽、他們為什麼會在這裡、跟誰來、原本想做什麼？
- 在真正出事前，讀者有沒有先喜歡上這個活動現場、記住幾個人、知道姊弟今天扮什麼角色？
- 這段誤導有沒有真的讓人先站錯邊，而不是只被輕輕懷疑一下？
- 這次是不是又把本來可以寫成偷偷搞事、搶風頭、故意亂動的案件，洗成普通手滑或小誤會？
- 到 final_accuse 前，答案是不是還留著一點模糊感，而不是第二輪就幾乎講完了？
- 如果有人自責，讀者能不能立刻知道他剛剛到底貼錯了什麼、拿錯了什麼、說錯了什麼？
- ending 的最後兩段是不是還活在現場裡，而不是忽然開始總結人生道理？
- 三個 endings 裡的做錯的人、原因、道歉對象有沒有完全對齊？

【輸出規則】
- 只輸出完整 JSON object
- 最外層只能有 meta, nodes

【語氣錨點（只學手感，不得照抄）】
{style}

【要潤句的 JSON】
{raw_json}
""".strip()

    # ============================================================
    # Repair
    # ============================================================

    def build_repair_prompt(self, *, raw_text: str, error: str, theme: str) -> str:
        """
        repair 的唯一目標：讓 validator 過。

        ✅ 兩種常見 repair：
        A) 開場段落不足：append-only 補到剛好 N 段
        B) 開場命中禁詞：不要做同義詞替換，改成「替換整個命中段落（\\n\\n 分段）」
        """
        style = extract_style_example(selector=f"repair:{theme}:{error}", focus="opening_event")

        m_paras = re.search(
            r"scene_01_start\.narration\s*至少\s*(\d+)\s*段，\s*目前\s*(\d+)\s*段",
            (error or ""),
        )

        opening_banned_all = self._opening_banned_all()
        opening_banned_text = "、".join(opening_banned_all) if opening_banned_all else "(none)"

        safe_patterns = "\n".join([f"- {s}" for s in (self.opening_safe_patterns or [])])

        # A) 開場段落不足 → append-only
        if m_paras:
            min_need = int(m_paras.group(1))
            cur = int(m_paras.group(2))
            add_n = max(0, min_need - cur)
            return f"""
你上一版 JSON 沒通過驗證：scene_01_start 段落不足。

# 驗證錯誤
{error}

theme={theme}

【絕對規則】
- 只輸出完整 JSON object（不要 markdown / code fence / 解釋）
- 最外層只能有 meta, nodes
- 只允許修改：nodes.scene_01_start.narration
- 只允許追加段落（append only），禁止刪除/改寫既有段落，禁止改其他任何節點

【追加目標】
- 目前段落數={cur}
- 必須追加段落數={add_n}
- 追加後必須剛好={min_need} 段（用 \\n\\n 分段計數）
- 追加段落仍必須完全不包含任何開場禁詞（包含引號/轉述/台詞）：{opening_banned_text}

【可學的安全句型示範（只學語氣/節奏，不可照抄）】
{safe_patterns}

【節奏錨點（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

【你要修補的 JSON（請就地追加後輸出完整 JSON）】
{raw_text}
""".strip()

        # B) 開場命中禁詞 → “替換段落”模式
        banned_word = ""
        m = re.search(r"\[scene_01_start\]\s*出現禁止詞：(.+)$", (error or "").strip())
        if m:
            banned_word = (m.group(1) or "").strip()

        offending_paras: List[str] = []
        try:
            obj = json.loads(raw_text)
            nodes = obj.get("nodes") if isinstance(obj, dict) else None
            s1 = nodes.get("scene_01_start") if isinstance(nodes, dict) else None
            nar = s1.get("narration") if isinstance(s1, dict) else None
            if isinstance(nar, str):
                paras = self.split_paragraphs(nar)
                for p in paras:
                    hits = []
                    if banned_word and (banned_word in p):
                        hits = [banned_word]
                    else:
                        hits = self._has_any_opening_banned(p)
                    if hits:
                        offending_paras.append(p)
        except Exception:
            pass

        offending_block = (
            "\n\n".join([f"【命中段落示例】\n{x}" for x in offending_paras[:2]])
            if offending_paras
            else "（未能自動擷取命中段落，你需要自行在 scene_01_start 的 \\n\\n 段落中找出含禁詞的段落）"
        )

        return f"""
你上一版 JSON 沒通過驗證：scene_01_start 命中開場禁詞。
這次不要做同義詞替換，請用「替換段落」的方式修好。

# 驗證錯誤
{error}

theme={theme}

【絕對規則】
- 只輸出完整 JSON object（不要 markdown / code fence / 解釋）
- 最外層只能有 meta, nodes
- 只允許修改：nodes.scene_01_start.narration
- 其他 nodes 完全不動（不要改 title/choices/節點 id/嫌疑人名字）

【你要做的事（一定照做）】
1) 把 scene_01_start.narration 用 \\n\\n 分段
2) 找出「包含任何開場禁詞」的段落（包含引號/括號/轉述/台詞）
3) 對每個命中段落：直接用「全新的一段」替換它（不是修句子）
   - 替換後段落仍需是日常/互動/搞笑/配角登場（不可進入事件、不可推理）
   - 每段 1~2 句
   - 每段仍要用「角色：內容」開頭，例如「旁白：/霏霏：/樂樂：/林老師：/樂樂的爸爸：/廣播阿姨阿秀：」
4) 替換完成後，再逐字掃描整個 scene_01_start，確保完全不含禁詞：
   {opening_banned_text}

【可學的安全句型示範（只學語氣/節奏，不可照抄）】
{safe_patterns}

【系統擷取到的命中段落（供你定位；若沒有就自己找）】
{offending_block}

【節奏錨點（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

【語氣錨點（只學語氣/段落，不得照抄）】
{style}

【你要修補的 JSON（請就地替換段落後輸出完整 JSON）】
{raw_text}
""".strip()

    # ============================================================
    # Enrich helpers
    # ============================================================

    def _extract_scene01_offending_paras(self, raw_json: str) -> Dict[str, Any]:
        """
        給 enrich_prompt 用：把 scene_01_start 命中禁詞的段落抓出來，讓模型「替換段落」而不是亂改全篇。
        回傳：
          {
            "hits": ["走散", ...],
            "offending_paras": ["段落原文", ...]
          }
        """
        hits: List[str] = []
        offending: List[str] = []
        try:
            obj = json.loads(raw_json)
            nodes = obj.get("nodes") if isinstance(obj, dict) else None
            s1 = nodes.get("scene_01_start") if isinstance(nodes, dict) else None
            nar = s1.get("narration") if isinstance(s1, dict) else None
            if isinstance(nar, str) and nar.strip():
                paras = self.split_paragraphs(nar)
                banned_all = self._opening_banned_all()
                for p in paras:
                    phits = [w for w in banned_all if w and (w in p)]
                    if phits:
                        hits.extend(phits)
                        offending.append(p)
        except Exception:
            pass

        hits = list(dict.fromkeys([h for h in hits if h]))
        offending = offending[:3]
        return {"hits": hits, "offending_paras": offending}

    # ============================================================
    # Enrich
    # ============================================================

    def build_enrich_prompt(self, *, raw_json: str, theme: str, rep: Dict[str, Any]) -> str:
        """
        enrich：只針對 reasons 指到的點做最小修改，不要重寫整篇。

        ✅ 特別針對 ending 不完整：
        - 用「6 段骨架」讓 AI 更穩過 gate
        - 並允許插入搞笑/互動（放在骨架指定位置）

        ✅ 特別針對 scene_01_start 禁詞：
        - 把命中段落抓出來，要求「整段替換」（不要同義詞替換），避免 enrich 卡住不修乾淨
        """
        reasons = rep.get("reasons") or []
        style = extract_style_example(
            selector=f"enrich:{theme}:{'|'.join(map(str, reasons))}",
            focus="human_twist",
        )
        reasons_text = "\n".join([f"- {r}" for r in reasons]) if reasons else "- (none)"

        opening_banned_all = self._opening_banned_all()
        reader_hint_banned = self.banned_reader_hint_patterns or []

        # ✅ 若理由含 scene_01_start 禁詞：提供命中段落，要求「替換段落」
        need_fix_scene01_banned = any(
            isinstance(r, str) and ("scene_01_start" in r and "開場禁詞" in r) for r in reasons
        )
        s01_fix_block = ""
        if need_fix_scene01_banned:
            info = self._extract_scene01_offending_paras(raw_json)
            hits = info.get("hits") or []
            offending_paras = info.get("offending_paras") or []
            offending_text = (
                "\n\n".join([f"【命中段落】\n{p}" for p in offending_paras])
                if offending_paras
                else "（未擷取到命中段落，請你自行找出含禁詞的段落）"
            )
            s01_fix_block = f"""
【scene_01_start 禁詞修補（必做）】
- 你只允許修改：nodes.scene_01_start.narration
- 修法：用 \\n\\n 分段後，找出包含禁詞的段落，對每個命中段落「整段替換」成全新的一段（不要在原句上做同義詞替換）
- 替換後仍然只能是日常互動/玩笑/配角登場，不要進事件、不推理、不緊張
- 修補後請自己逐字掃描一次，確保命中數 = 0

命中的禁詞（供你對照）：{", ".join(hits) if hits else "(unknown)"}

系統擷取到的命中段落（供你定位）：
{offending_text}
""".strip()

        need_endings: List[str] = []
        for eid in ("scene_10_ending_clear", "scene_10_ending_nudge", "scene_10_ending_defer"):
            for r in reasons:
                if eid in r:
                    need_endings.append(eid)
                    break
        need_endings = list(dict.fromkeys(need_endings))

        ending_focus = ""
        if need_endings:
            ending_focus = f"""
【本次結尾修補指令（最重要）】
- 你只需要修改以下 ending 節點的 narration（其他節點不動）：{", ".join(need_endings)}
- 每個被修的 ending narration 必須用 \\n\\n 分成「至少 {self.ending_min_paragraphs} 段」
- 強烈建議用固定骨架（每段 1~2 句，短短就好）：
  1) 收尾情境（大家回到安全、有人協助）
  2) 原因（必須含：因為/所以/原來/其實是 其中之一）
  3) 搞笑/互動（霏霏吐槽、樂樂誇張，或配角插話；但不要破壞事件事實）
  4) 道歉（必須含：對不起/抱歉/道歉 其中之一）
  5) 後續怎麼收/下次怎麼做（建議含：下次/以後/記得/提醒/先說/先問）
  6) 餘韻（和好、回到日常、結尾暖暖的）
- 注意：原因 / 道歉 / 後續怎麼收 這三件事「不要省略」，最好分開段落寫，最穩。
- 不要把最後一段寫成「大家學到……的重要性」這種品德摘要；要讓事情真的收在現場裡。
- 如果這次的惡作劇或動手腳差點釀成比較大的麻煩，可以讓老師、站務員、家長或工作人員接手，帶去了解、安撫、說明、通知家長或暫時帶離現場，但不要寫成可怕懲罰、威脅或刑罰口氣。
""".strip()

        accuse_focus = ""
        if any(
            ("嫌疑人未在指認前登場" in str(r))
            or ("嫌疑人名字太泛或像 placeholder" in str(r))
            or ("final_accuse narration 不得提到嫌疑人名字" in str(r))
            or ("final_accuse choices" in str(r))
            for r in reasons
        ):
            accuse_focus = f"""
【本次指認節點修補指令（必做）】
- 你至少要修改：nodes.final_accuse；必要時可連帶修改 three endings 的 narration，讓人名與真相一致
- final_accuse 前 3 個 choice text 必須是「前文真的出現過的人名」，不能寫成「那個同學 / 那個攤位的人 / 在旁邊觀望的同學 / 某個人」這種泛稱
- 第 4 個 choice text 必須完全保留：{self.unsure_choice_text}
- final_accuse.narration 不能提到任何嫌疑人名字，也不要直接出現第 4 個選項完整字串
- 如果你重選了嫌疑人名字，請同步檢查 solution_index 與 three endings 是否還在講同一件事
""".strip()

        naming_focus = ""
        if any(
            ("placeholder/佔位命名" in str(r))
            or ("配角稱呼太泛" in str(r))
            or ("嫌疑人名字太泛或像 placeholder" in str(r))
            for r in reasons
        ):
            naming_focus = f"""
【本次配角命名修補指令（必做）】
- 把所有像「老師A / 爸爸B / 志工2 / 主持人甲」這種 placeholder，改成自然名字或關係稱呼
- 也不要只寫成「老師：/ 爸爸：/ 媽媽：/ 店員：/ 大人：」這種太泛的 speaker label
- 可接受的寫法例子：林老師、樂樂的爸爸、廣播阿姨阿秀、氣球攤老闆阿發
- 改名時要前後一致：前文、指認、three endings 都要是同一個人
""".strip()

        memorable_name_focus = ""
        if any("配角名字記憶點偏弱" in str(r) for r in reasons):
            memorable_name_focus = f"""
【本次配角名字記憶點修補指令（必做）】
- 你至少要修改：scene_01_start 與 warmup 前半；必要時可連帶修改嫌疑人名字與 three endings，讓人名前後一致
- 不要把所有孩子都寫成普通本名。至少留 1 到 2 個一聽就記得住的名字，偏可愛綽號式或外號式也可以
- 可接受的方向例子：鉛筆小白、狐狸小右、糖果小莓、廣播阿姨阿秀、點心叔叔阿發
- 名字要好叫、好記、自然，不要寫成奇幻稱號、網名或過度中二的代號
- 第一次提到時，仍然要一起交代關係/職責/當下動作，不要只換名字不補關係
""".strip()

        incident_focus = ""
        if any(
            isinstance(r, str) and (
                f"{self.incident_node_id} 太像把麻煩自己收掉" in r
                or f"{self.incident_node_id} 缺少明確要查清楚的麻煩" in r
            )
            for r in reasons
        ):
            incident_focus = f"""
【本次事件節點修補指令（必做）】
- 你只需要修改：nodes.{self.incident_node_id}.narration
- 這個節點結束時，麻煩必須還留著，不能自己收掉
- 必須讓至少一個已登場角色明確說出：哪裡不對、少了什麼、誰說法兜不起來、或為什麼大家開始急
- 不要把事件寫成只是看到一個東西、順手幫個小忙、或大家立刻又開心起來
- 可以補一個尷尬、嘴硬、遮掩、誤會或愛面子的反應，讓後面真的有得查
""".strip()

        background_focus = ""
        if any("開場場面太小" in str(r) for r in reasons):
            background_focus = f"""
【本次背景規模修補指令（必做）】
- 你只需要修改：scene_01_start / scene_01_warmup_2 / scene_01_warmup_3 的 narration
- 把背景從「單一角落」擴成「一整個正在進行的活動場域」
- 開場到 warmup 至少要清楚帶出 3 個公共元素/動線，例如舞台、報到桌、攤位、後台、隊伍、廣播、評審席、計分桌
- 如果場地平常偏安靜，例如圖書館/博物館，請補出今天為何特別熱鬧，不要讓舞台或喧鬧像憑空冒出來
- 不要只增加名詞，要讓霏霏、樂樂真的在這些區域之間移動、看到人、聽到廣播、被活動節奏推著走
""".strip()

        opening_generic_focus = ""
        if any(
            ("scene_01_start 首段太像總覽口播" in str(r))
            or ("scene_01_start 第一段還沒有先讓人出現" in str(r))
            for r in reasons
        ):
            opening_generic_focus = f"""
【本次開場首段修補指令（必做）】
- 你至少要修改：scene_01_start 的第一段；必要時可連帶微調後面 1~2 段讓銜接更順
- 可以先交代「一年一度的什麼活動 / 今天這裡正在辦什麼」，但不要只有導覽口播
- 第一段最好同時帶活動名字、具體區域和一個正在發生的動作：某個人正在忙、某句話正在飛、某個區域正在卡、某個配角正在出糗
- 第一個畫面最好是「人先出現」，例如某個配角正在扛東西跑、正在擦汗找人、正在和另一個人拌嘴；不要讓第一句完整停在「一年一度的什麼活動今天開始了」
- 如果第一段還沒有具體的人在做事，就重寫到有為止；不要只用燈光、旗子、天氣、熱鬧程度撐第一段
- 盡量不要用「今天這裡正在舉辦……」純背景起手；更像樣本的是先見到人，再順手知道今天在辦什麼
- 要有觸手可摸的東西，不要只做空拍總覽或只剩活動簡介
""".strip()

        arrival_focus = ""
        if any("scene_01_start 缺少到場理由/同行關係" in str(r) for r in reasons):
            arrival_focus = f"""
【本次到場理由修補指令（必做）】
- 你至少要修改：scene_01_start 前 3 到 5 段；必要時可連帶微調 scene_01_warmup_2 的第一段
- 讓讀者自然知道：霏霏和樂樂今天為什麼會來這裡、跟誰來、原本是來玩/來住/來參加/來幫忙什麼、今天被分到什麼或正在排哪個流程
- 不要硬塞導覽旁白，要把資訊長在人物嘴上、家人/老師的互動、手上拿的東西、排隊或報到動作裡
- 目標不是補背景資料，而是讓讀者知道兩人不是憑空掉進場景裡
""".strip()

        setup_focus = ""
        if any("前段鋪墊太短" in str(r) for r in reasons):
            setup_focus = f"""
【本次前段鋪陳修補指令（必做）】
- 你至少要修改：scene_01_start 與兩個 warmup；必要時可把原本太快跑進事件的資訊往後挪
- 在真正出事前，先讓讀者記住幾個人、知道今天是什麼活動、現場有哪些區域/比賽/流程、霏霏樂樂今天扮什麼角色
- 可以補更多姊弟打鬧、配角出場、今天的任務與想做的事，讓場子更有溫度，再讓事件闖進來
- 事件前最好先有 2 到 3 輪真的在互動的對話，不要只有旁白帶資訊
- 不要只是灌水；每多一段都要讓角色更鮮、場合更立得住、後面線索更有根
""".strip()

        stakes_focus = ""
        if any("案件規模太小" in str(r) for r in reasons):
            stakes_focus = f"""
【本次案件規模修補指令（必做）】
- 你至少要修改：nodes.{self.incident_node_id}，必要時可連帶修改 scene_03_check_1 / scene_04_check_2 / scene_05_check_3 / scene_06_hypothesis_1
- 把案件改成會牽動活動流程/公開場面/面子/上台安排的麻煩
- 不要再只是普通私人物品找不到；要讓角色明白如果不弄清楚，接下來的表演/比賽/廣播/闖關/報到會卡住，或有人會當場難堪
- 仍然維持同一個場景主題，不要把活動整個換掉
""".strip()

        cast_focus = ""
        if any(("配角存在感不足" in str(r)) or ("配角關係交代不足" in str(r)) for r in reasons):
            cast_focus = f"""
【本次配角鮮明度修補指令（必做）】
- 你至少要修改：scene_01_start 與 warmup 節點；必要時可連帶修改 incident 前後的對話
- 不要只用旁白幫配角下定義；讓配角第一次開口就帶出脾氣、毛病、焦慮、愛現或嘴硬
- 至少讓 3 個配角/大人具名或有關係稱呼，而且一出場就能分辨誰急、誰愛搶、誰會逞強、誰怕丟臉
- 配角第一次出場時，要順手交代他跟主角或活動的關係，例如同班同學、隔壁班對手、去年冠軍、站務員、主持人、隔壁攤老闆，不要只丟名字讓讀者自己猜
- 不要把配角都寫成功能型 NPC 或同一種溫柔配音員口氣
""".strip()

        cast_intro_focus = ""
        if any("配角第一次出場太跳" in str(r) for r in reasons):
            cast_intro_focus = f"""
【本次配角初登場修補指令（必做）】
- 你至少要修改：scene_01_start 與 warmup 前半；必要時可連帶微調第一次提到嫌疑人的那幾段
- 不要讓陌生名字直接冒出來。第一次提到時，最好就寫成「關係/職責 + 名字 + 當下動作」
- 例如不是只寫「阿棠跑過來」，而是要更像「霏霏的同學阿棠抱著號碼牌跑過來」
- final_accuse 前那三個嫌疑人，也要在前半先讓讀者知道：他是誰、為什麼在這裡、跟哪個區域或哪個人靠得近
""".strip()

        mislead_focus = ""
        if any(("誤導層次偏弱" in str(r)) or ("後段翻盤不夠狠" in str(r)) for r in reasons):
            mislead_focus = f"""
【本次誤導強度修補指令（必做）】
- 你至少要修改：incident 後面的 check / hypothesis 節點
- 至少做出一個「先看起來真的很像他做的」錯方向，不要只是有人隨口被懷疑一下
- 再補一個能把第一層懷疑翻掉的說法、時間差或遮掩，讓讀者暫時站錯邊
- scene_05_check_3 不能只是確認前面那條線，而是要再丟一個差點把答案翻走的新方向
- scene_06_hypothesis_1 至少要保留兩條還能成立一半的解釋，不能只剩單一路線
- 誤導要跟人物毛病連在一起，例如逞強、護短、怕被笑、愛搶功、怕丟臉，不要只靠物證小碎片
""".strip()

        ambiguity_focus = ""
        if any(
            ("調查太快變清楚" in str(r))
            or ("scene_05_check_3 太快定調嫌疑人" in str(r))
            or ("scene_06_hypothesis_1 太快定調嫌疑人" in str(r))
            for r in reasons
        ):
            ambiguity_focus = f"""
【本次調查模糊感修補指令（必做）】
- 你至少要修改：scene_03_check_1 / scene_04_check_2 / scene_05_check_3 / scene_06_hypothesis_1
- 調查每一輪都要像樣本那樣「有方向，但還不能拍板」；不要在第三輪前後就讓答案只剩一個
- 至少保留兩個說得通一半的方向：一個看起來像真的、一個能把前面翻掉，但都還差最後一點
- scene_06_hypothesis_1 只能是不完整猜想，不能寫成「就是他」或幾乎等於揭曉答案
- scene_05_check_3 也不能出現「一定是 / 就是他 / 果然是 / 八成是」這種拍板詞，請改成「好像 / 也可能 / 說不準 / 目前看起來」這類還留有空間的說法
- 多用「也可能 / 好像 / 可是 / 不一定 / 或許」這種模糊但帶方向的句子，讓讀者跟著搖擺
""".strip()

        villain_scale_focus = ""
        if any("案件太像純忙中出錯/小誤會" in str(r) for r in reasons):
            villain_scale_focus = f"""
【本次案件力道修補指令（必做）】
- 你至少要修改：incident 與 incident 後面的 check / hypothesis 節點；必要時可連帶微調 warmup，讓前面先埋不甘心、嫉妒、搶風頭、偷偷亂動的情緒
- 不要再把事情收成單純手忙腳亂。更像樣本的是：有人故意亂動、偷偷藏、偷改、想害別人出糗、想搶表現、想卡掉別人的機會
- 尺度仍然是兒童故事，不用黑暗，但一定要有「他就是故意弄一下」的主動性
- 可以讓他本來只想惡作劇一下，但後果比他預想的大，例如差點害人受傷、差點打翻燙的東西、差點扯倒道具、差點撞壞設備、差點讓舞台或流程被迫喊停，讓現場不得不由大人接手
- 如果真相裡本來就有失手，也請再往前補出：為什麼他要先偷動、先硬撐、先遮掩，而不是只有事後道歉
""".strip()

        consequence_focus = ""
        if any("案件後果太輕" in str(r) for r in reasons):
            consequence_focus = f"""
【本次案件後果修補指令（必做）】
- 你至少要修改：incident 與 incident 後面的 check / hypothesis；必要時可微調 ending
- 壞事起點可以還是孩子氣惡作劇，但後果不能只像小小搗蛋；要長成差點釀成更大麻煩
- 可以是差點害人跌倒、差點打翻熱食、差點扯倒道具、差點撞壞設備、差點闖進危險區、差點錯過大流程、差點讓現場整段停住
- 不用寫成真的受重傷或可怕事故，但要讓角色意識到：這已經不是普通玩笑
""".strip()

        queue_focus = ""
        if any("核心麻煩又縮成排隊/順位糾紛" in str(r) for r in reasons):
            queue_focus = f"""
【本次核心事件修補指令（必做）】
- 你至少要修改：incident 與 incident 後面的 check / hypothesis；必要時可微調 warmup，把原本的隊伍/順序問題降成表面現象
- 不要再把核心衝突收成插隊、換位、誰排前面這種糾紛
- 如果要保留隊伍或順序，只能把它當成第一層假象；真正要查的核心，必須是更大的破壞、危險或偷動手腳，例如有人動了設備、亂了安全動線、差點害人受傷、差點讓主流程喊停
- 保持同一個場景與已登場人物，不要整篇換案
""".strip()

        adult_takeover_focus = ""
        if any("結尾缺少大人接手收場" in str(r) for r in reasons):
            adult_takeover_focus = f"""
【本次大人接手收尾修補指令（必做）】
- 你至少要修改：three endings 的 narration
- 如果事情差點鬧大，請補出老師、家長、站務員或工作人員如何把現場穩住
- 可以是把人帶到旁邊了解、安撫被波及的人、說明後續、通知家長、暫時帶離現場
- 不要寫成恐嚇、重罰、刑罰，也不要只有一句「下次不要這樣了」就結束
""".strip()

        admission_focus = ""
        if any("前因交代太跳" in str(r) for r in reasons):
            admission_focus = f"""
【本次前因落地修補指令（必做）】
- 你至少要修改：出現自責/補述的那一兩段；必要時可連帶微調前一段
- 如果角色要說「我的疏忽 / 我的錯 / 我剛剛太忙了」，同一段或前一段就先講清楚他剛剛把什麼貼錯、拿錯、放錯、報錯，害到誰或卡到哪個流程
- 不要只丟抽象自責；要讓讀者一聽就知道那個人到底做了哪個動作，為什麼現在在補鍋
""".strip()

        generic_focus = ""
        if any("出現空泛 AI 說書套句" in str(r) for r in reasons):
            generic_focus = f"""
【本次空泛說書句修補指令（必做）】
- 你至少要修改：scene_01_start；必要時可連帶修改 warmup 節點與 endings 中同類型空話
- 直接把空泛句整句重寫，不要只刪掉形容詞
- 改寫後每一段至少要帶出一個「人 + 動作」或「區域 + 發生中的事」，不要只剩氣氛形容
- 以下這類句子都要避開：{", ".join((self.banned_generic_prose_patterns or [])[:12])}
- 場景要像它自己，不要寫成 generic 園遊會口播；要讓讀者知道誰在忙、哪裡在卡、什麼區域正在動
""".strip()

        return f"""
你是「故事 JSON 修補師」。目標是：用最小修改把 JSON 修到通過 gate。

theme={theme}

【絕對規則】
- 只輸出完整 JSON object（不要 markdown / code fence / 解釋）
- 不要重寫整篇：只針對 reasons 指到的點修
- 保持單一主題，不要換場景
- 為了讓故事比較像樣本，你可以微調 opening / warmup / incident / check / hypothesis 的 narration，但不要亂改 choices 和節點結構

【本次 gate 失敗原因（逐條修掉）】
{reasons_text}

【提醒：開場禁詞（scene_01_start 任何位置都不得出現；只擋直接破案/審訊口氣，包含引號/轉述/台詞）】
{", ".join(opening_banned_all)}

{s01_fix_block}

【全篇禁止（孩子自己判斷/記住，不要替讀者總結排除）】
{", ".join(reader_hint_banned)}

{naming_focus}

{memorable_name_focus}

{opening_generic_focus}

{arrival_focus}

{setup_focus}

{background_focus}

{incident_focus}

{stakes_focus}

{cast_focus}

{cast_intro_focus}

{mislead_focus}

{ambiguity_focus}

{villain_scale_focus}

{consequence_focus}

{queue_focus}

{adult_takeover_focus}

{admission_focus}

{generic_focus}

{accuse_focus}

{ending_focus}

【禁止對讀者下指令】
- 不要出現：{", ".join(self.gamey_patterns or [])}

【大型開場錨點（只學節奏，不得照抄）】
{GOLDEN_OPENING_EXAMPLE}

【樣本錨點（只學語氣/段落，不得照抄）】
{style}

【你要修補的 JSON（請就地修改後輸出完整 JSON）】
{raw_json}
""".strip()

    def build_endings_repair_prompt(self, *, raw_json: str, theme: str, ending_ids: List[str]) -> str:
        style = extract_style_example(
            selector=f"ending:{theme}:{','.join(ending_ids)}",
            focus="human_twist",
        )
        targets = ", ".join(ending_ids)
        true_suspect = ""
        try:
            obj = json.loads(raw_json)
            nodes = obj.get("nodes") if isinstance(obj, dict) else None
            fa = nodes.get("final_accuse") if isinstance(nodes, dict) else None
            choices = fa.get("choices") if isinstance(fa, dict) else None
            solution_index = fa.get("solution_index") if isinstance(fa, dict) else None
            if isinstance(choices, list) and solution_index in (0, 1, 2):
                choice = choices[int(solution_index)]
                if isinstance(choice, dict):
                    true_suspect = str(choice.get("text") or "").strip()
        except Exception:
            true_suspect = ""

        truth_line = (
            f"- 這個故事目前的正解嫌疑人是：{true_suspect}。如果 ending 內有提到人名，三個 endings 都必須對齊這個人。\n"
            if true_suspect
            else ""
        )
        return f"""
你是「故事結尾修補師」。
你只修指定 ending 的 narration，其他任何欄位都不准改。

theme={theme}

【絕對規則】
- 只輸出 JSON object，格式必須是：
  {{
    "scene_10_ending_clear": "....",
    "scene_10_ending_nudge": "...."
  }}
- key 只能包含這次要修的 ending node id：{targets}
- 不要輸出 meta、不要輸出 nodes、不要解釋、不要 markdown

【你要做的事】
- 只為以下節點重寫 narration：{targets}
- 每個 narration 都必須用 \\n\\n 分成至少 {self.ending_min_paragraphs} 段
- 三個 endings 必須說同一件事的同一個真相，不准換人、不准換原因
{truth_line}- 如果 clear 已經說出真相，nudge / defer 也要對齊同一個真相，只是帶領方式不同
- 每個 ending 都要明確包含：
  1) 原因（必須有：因為 / 所以 / 原來 / 其實 其中之一）
  2) 道歉（必須有：對不起 / 抱歉 / 道歉 其中之一）
  3) 後續怎麼收 / 下次怎麼做（建議有：下次 / 以後 / 記得 / 提醒 / 先說 / 先問）
- clear / nudge / defer 的差別只在帶領方式，不在事件事實
- 不要寫成空泛慶祝，不要出現「這真是一個美好的日子」「每一天都充滿歡樂」這類套句
- 不要寫成「大家學到……的重要性」這種品德摘要
- 如果事情已經差點造成更大的麻煩，可以寫大人把人帶去了解、請老師或家長接手、暫時帶離現場說明，但不要用可怕懲罰、威脅或嚇小孩的口氣
- 可以保留孩子氣與玩笑，但要長在同一件事件裡，不要另外發明新插曲

【角色提醒】
- 霏霏像會笑著把場面接住的姊姊，不是訓話老師
- 樂樂可以插一小句反應，但不要搶走真相

【語氣錨點（只學手感，不得照抄）】
{style}

【你要參考的完整 JSON】
{raw_json}
""".strip()
