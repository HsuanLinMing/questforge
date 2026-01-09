from __future__ import annotations

import uuid
from typing import List

from questforge.ai.ai_client import AiClient


from .schemas import (
    ResponsePackage,
    ResponseRequest,
    StoryCharacter,
    StoryObservation,
    StoryPackage,
    StoryScene,
)


def _two_to_four_sentences(text: str) -> str:
    # Very small safeguard: keep it short-ish.
    # (You can harden later.)
    return text.strip()


class MockAiClient(AiClient):
    """Offline mock AI.
    Goal: make the engine runnable without any external calls.
    """

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

    def generate_response(self, req: ResponseRequest) -> ResponsePackage:
        # IMPORTANT: Keep responses short, observation-focused, no answers.
        role_prefix = {
            "narrator": "",
            "feifei": "霏霏：",
            "lele": "樂樂：",
            "teacher": "老師：",
        }.get(req.role, "")

        if req.intent == "support_uncertain":
            text = (
                "沒關係，有時候事情真的不那麼清楚。\n"
                "你願意說不確定，代表你很小心。\n"
                "我們先把看到的整理好，交給老師也很安全。"
            )
        elif req.intent == "acknowledge_observation":
            obs = (req.selected_observations[0] if req.selected_observations else req.player_text).strip()
            if not obs:
                obs = "你剛剛注意到的那個小細節"
            text = (
                f"我聽到你注意到的是：『{obs}』。\n"
                "我們先把這個小細節記下來。\n"
                "這只是目前的想法，之後可以一起討論。。"
            )
        elif req.intent == "safe_redirect_after_accuse":
            name = req.accused_name.strip() or "那位同學"
            text = (
                f"謝謝你說出你的想法。\n"
                f"我們先說看到的，不要急著下結論。\n"
                f"現在把線索交給老師確認會更安全，你也可以選『我還不確定』。"
            )
        elif req.intent == "reflect_reasoning":
            text = (
                "我們回頭看：你用了哪些觀察？\n"
                "這不是判對錯，是幫你整理思路。\n"
                "如果還不確定，也可以把不確定交給老師。"
            )
        elif req.intent == "recall_event":
            text = (
                "我們來回想一下剛剛發生了什麼。\n"
                "你想選哪一個都可以，重點是想起來。\n"
                "不確定也可以跳過。"
            )
        elif req.intent == "replay_context":
            text = (
                "我們回頭再看一次剛剛的畫面，看看有沒有漏掉的小細節。\n"
                "這不是重來，是重新理解。"
            )
        else:
            # fallback: still safe
            text = "沒關係，我們先把看到的整理好，不急。"

        text = _two_to_four_sentences(text)
        if role_prefix:
            text = role_prefix + text

        return ResponsePackage(intent=req.intent, role=req.role, text=text)
