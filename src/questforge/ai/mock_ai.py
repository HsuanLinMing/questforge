# src/questforge/ai/mock_ai.py
from __future__ import annotations

import random
import uuid
from typing import List

from questforge.ai.ai_client import AiClient
from questforge.ai.response_guard import guard_response
from questforge.ai.schemas import (
    ResponsePackage,
    ResponseRequest,
    StoryCharacter,
    StoryObservation,
    StoryPackage,
    StoryScene,
)


def _clean_lines(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _clamp_style(text: str) -> str:
    """Soft guard: 2~4 lines, <=1 question mark."""
    lines = _clean_lines(text)
    if len(lines) > 4:
        lines = lines[:4]

    q = 0
    out: List[str] = []
    for ln in lines:
        q += ln.count("？") + ln.count("?")
        out.append(ln)
        if q > 1:
            break

    return "\n".join(out).strip()


class MockAiClient(AiClient):
    """Offline mock AI (kid-friendly).
    Goal: make the engine runnable without any external calls.
    """

    # --------------------------
    # Story (fixed mock content)
    # --------------------------
    def generate_story(self) -> StoryPackage:
        case_id = f"mock-{uuid.uuid4().hex[:8]}"

        characters = [
            StoryCharacter(name="霏霏", role="霏霏", notes="姊姊型，慢慢陪想，提醒停一下"),
            StoryCharacter(name="樂樂", role="樂樂", notes="弟弟型，有點緊張但願意說感覺"),
            StoryCharacter(name="小杰", role="同學", notes="一直抱著自己的運動護照"),
            StoryCharacter(name="小安", role="同學", notes="手上拿著水壺，常常回頭看攤位"),
            StoryCharacter(name="老師", role="老師", notes="穩定，會接住情緒，說會一起確認"),
        ]

        prologue = (
            "今天是學校的小小活動日。大家在走廊排隊，要去『集章小攤位』蓋章。\n"
            "規則是：每個人輪到自己時，才可以把運動護照拿給老師蓋一個章。\n"
            "這件事很重要，因為大家都想把章集滿，換一張小貼紙。"
        )

        scenes: List[StoryScene] = [
            StoryScene(
                title="走廊排隊",
                narration=(
                    "走廊上有一條長長的隊伍。樂樂站在霏霏旁邊，手上捏著自己的運動護照。\n"
                    "前面的小杰一直把護照抱在胸前，小安則一直回頭看攤位那邊。"
                ),
                observations=[
                    StoryObservation("小杰一直抱著運動護照，抱得很緊。"),
                    StoryObservation("小安回頭看了好幾次攤位的桌子。"),
                ],
            ),
            StoryScene(
                title="輪到樂樂前",
                narration=(
                    "隊伍慢慢往前。桌上放著印章、印泥，旁邊還有一疊小貼紙。\n"
                    "樂樂聽到有人說：『咦？剛剛那張貼紙不是在這裡嗎？』"
                ),
                observations=[
                    StoryObservation("桌上有印章、印泥，旁邊有一疊小貼紙。"),
                    StoryObservation("有人說：『剛剛那張貼紙不是在這裡嗎？』"),
                ],
            ),
            StoryScene(
                title="樂樂心裡怪怪的",
                narration=(
                    "樂樂看了一眼桌邊的角落，又看了一眼隊伍旁邊的小椅子。\n"
                    "他覺得心裡怪怪的，但他先忍住沒有說。"
                ),
                observations=[
                    StoryObservation("樂樂看了桌邊角落，又看了旁邊的小椅子。"),
                ],
            ),
        ]

        cooldown_dialogue = (
            "樂樂小聲說：『我有點不舒服…我不知道該不該說。』\n"
            "霏霏說：『我們先停一下，先說你看到什麼就好。』\n"
            "霏霏又說：『如果還不確定，我們可以找老師一起確認。』"
        )

        teacher_scene = (
            "老師走過來，蹲下來聽大家說。\n"
            "老師說：『謝謝你們願意說看到的事，我們一起把桌子附近再看一遍。』\n"
            "老師也說：『不急著下結論，先把事情安全接住。』"
        )

        open_ending = (
            "大家跟著老師一起慢慢查看桌邊和椅子附近。\n"
            "樂樂覺得自己沒有急著指人，心裡比較安穩。\n"
            "老師說會再確認清楚，讓每個人都被好好照顧。"
        )

        return StoryPackage(
            case_id=case_id,
            title="走廊的集章小貼紙",
            prologue=prologue,
            characters=characters,
            scenes=scenes,
            cooldown_dialogue=cooldown_dialogue,
            teacher_scene=teacher_scene,
            open_ending=open_ending,
            tags=["排隊", "輪流", "貼紙", "集章"],
        )

    # --------------------------
    # Response (whitelist intents)
    # --------------------------
    def generate_response(self, req: ResponseRequest) -> ResponsePackage:
        role_prefix = {
            "narrator": "",
            "feifei": "霏霏：",
            "lele": "樂樂：",
            "teacher": "老師：",
        }.get(req.role, "")

        def pick(lines: List[str]) -> str:
            return random.choice(lines).strip()

        def pick_best(candidates: List[str]) -> str:
            """挑最乾淨的台詞（ok 且 warnings 最少）；找不到就用 fallback。"""
            best_text = ""
            best_warn = 10**9

            for _ in range(10):
                raw = _clamp_style(pick(candidates))
                text = (role_prefix + raw) if role_prefix else raw

                gr = guard_response(text)
                if not gr.ok:
                    continue

                wc = len(gr.warnings or [])
                if wc < best_warn:
                    best_warn = wc
                    best_text = text
                    if wc == 0:
                        break

            if best_text:
                return best_text

            fallback = "我先把看到的收好。\n不急，我們慢慢走。\n需要的話就找老師一起確認。"
            raw = _clamp_style(fallback)
            return (role_prefix + raw) if role_prefix else raw

        # --------------------------
        # FEIFEI
        # --------------------------
        FEIFEI_SUPPORT_UNCERTAIN = [
            "嗯～事情有時候真的會霧霧的。\n你願意說不確定，代表你很小心。\n我們先把看到的收好就行。",
            "等等，我差點把重點忘記寫進小本本。\n你說不確定很重要，因為這樣比較安全。\n我們慢慢來。",
            "沒關係～小偵探也會遇到『看不清楚』的時候。\n先停一下、先呼吸一下。\n我們也可以找老師一起確認。",
        ]

        FEIFEI_ACK_OBS = [
            "我聽到你注意到的是：『{obs}』。\n我先幫你放進觀察小口袋。\n等等再一起拿出來看看。",
            "欸對，我剛剛也有瞄到這個！\n『{obs}』先記著。\n不用急著把故事講完美。",
            "收到～『{obs}』我先貼在便利貼上。\n貼歪了也沒關係，之後可以再換位置。",
        ]

        FEIFEI_REFLECT = [
            "我們來做『線索排隊』～一個一個站好。\n不是要答對，只是把想法變清楚。\n你已經很像小偵探了。",
            "等等，我腦袋剛剛差點打結。\n我們回頭看看：你用了哪些觀察？\n不確定也沒關係。",
            "我先幫你把觀察擺整齊。\n我們只說看到的，不急著下結論。\n這樣最安全。",
        ]

        FEIFEI_SAFE_REDIRECT = [
            "收到你的想法～\n我們先說看到的，不要急著貼標籤。\n老師會跟我們一起確認。",
            "你願意說出來很勇敢。\n不過我們先用『觀察』說話。\n接下來交給老師一起看最安全。",
            "好～我先把你的想法放在桌上，不讓它亂跑。\n我們先說看到的。\n等等請老師一起幫忙確認。",
        ]

        FEIFEI_REPLAY = [
            "好～倒帶！\n我們再看一次剛剛那個畫面。\n看看有沒有漏掉的小細節。",
            "重播一遍也很厲害。\n因為小偵探最會『回頭看』。\n走～再看一次。",
            "OK！我把時間遙控器按回去。\n不是真的重來，是重新理解。\n準備好就出發。",
        ]

        FEIFEI_BACK_FROM_CLUES = [
            "線索小抽屜關好～我們回到『{scene}』繼續看。\n看看哪個小細節會自己冒出來。",
            "好，線索我先幫你放口袋。\n回到『{scene}』，再走一步看看！",
            "線索看完啦～\n回『{scene}』繼續。\n我剛剛差點把抽屜關到自己手…沒事！",
        ]

        FEIFEI_BACK_FROM_NOTES = [
            "筆記收好收好～\n回到『{scene}』，我們繼續當小偵探。",
            "OK～你寫的都算數。\n回『{scene}』繼續出發！",
            "筆記像小地圖。\n回『{scene}』，我們照著走就不會迷路。",
        ]

        FEIFEI_BACK_FROM_SAVES = [
            "存檔都整理好了～\n回到『{scene}』，故事繼續！",
            "好耶，有備份就安心。\n回『{scene}』，我們走～",
            "存檔像把冒險塞進口袋。\n回『{scene}』繼續。\n（我不會再把口袋翻過來了！）",
        ]

        FEIFEI_GENERIC_OK = [
            "嗯～我們先把看到的收好。\n不急，慢慢來就好。",
            "先停一下也可以。\n我們用觀察慢慢走。",
            "好～我們先往安全的方向走。\n不需要立刻下結論。",
        ]

        # --------------------------
        # LELE
        # --------------------------
        LELE_REFLECT = [
            "欸我剛剛腦袋轉太快，差點自己絆倒自己。\n我們慢慢看比較不會撞牆。\n嘿嘿。",
            "我有一點想亂猜…但霏霏會瞪我。\n所以我先乖乖看線索。\n我很乖吧？",
            "我覺得我像在溜滑梯，滑太快了。\n先停一下、看清楚比較安全。",
        ]

        # --------------------------
        # TEACHER
        # --------------------------
        TEACHER_SAFE = [
            "謝謝你們願意把看到的說出來。\n我們一起再確認，不急。\n先照顧好自己最重要。",
            "你們做得很好：先說觀察、不急著下結論。\n接下來我會陪你們一起確認。\n我們慢慢來。",
        ]

        # --------------------------
        # Intent routing
        # --------------------------
        if req.intent == "support_uncertain":
            text = pick_best(FEIFEI_SUPPORT_UNCERTAIN)

        elif req.intent == "acknowledge_observation":
            obs = (
                req.selected_observations[0]
                if req.selected_observations
                else req.player_text or "那個小細節"
            ).strip()
            candidates = [s.format(obs=obs) for s in FEIFEI_ACK_OBS]
            text = pick_best(candidates)

        elif req.intent == "reflect_reasoning":
            if random.random() < 0.35:
                text = pick_best(LELE_REFLECT)
            else:
                text = pick_best(FEIFEI_REFLECT)

        elif req.intent == "safe_redirect_after_accuse":
            if req.role == "teacher":
                text = pick_best(TEACHER_SAFE)
            else:
                text = pick_best(FEIFEI_SAFE_REDIRECT)

        elif req.intent == "replay_context":
            text = pick_best(FEIFEI_REPLAY)

        elif req.intent == "back_from_clues":
            scene = (req.scene_title or "這一段").strip()
            candidates = [s.format(scene=scene) for s in FEIFEI_BACK_FROM_CLUES]
            text = pick_best(candidates)

        elif req.intent == "back_from_notes":
            scene = (req.scene_title or "這一段").strip()
            candidates = [s.format(scene=scene) for s in FEIFEI_BACK_FROM_NOTES]
            text = pick_best(candidates)

        elif req.intent == "back_from_saves":
            scene = (req.scene_title or "這一段").strip()
            candidates = [s.format(scene=scene) for s in FEIFEI_BACK_FROM_SAVES]
            text = pick_best(candidates)

        else:
            text = pick_best(FEIFEI_GENERIC_OK)

        # --- Day13-D: Mock Guard (print warnings only; do not block flow) ---
        gr = guard_response(text)
        if (not gr.ok) or gr.warnings:
            print("\n[AI 白名單檢查]")
            if not gr.ok:
                for e in gr.errors:
                    print(f"  ❌ {e}")
            for w in gr.warnings:
                print(f"  ⚠️ {w}")

        return ResponsePackage(intent=req.intent, role=req.role, text=text.strip())
