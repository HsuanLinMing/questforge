from __future__ import annotations

from abc import ABC, abstractmethod
import random
from .schemas import ResponsePackage, ResponseRequest, StoryPackage


class AiClient(ABC):
    """AI boundary interface.

    - Story generation: produce structured StoryPackage.
    - Response generation: produce short safe ResponsePackage (whitelist intent).
    """

    @abstractmethod
    def generate_story(self) -> StoryPackage:
        raise NotImplementedError

    @abstractmethod
    def generate_response(self, req: ResponseRequest) -> ResponsePackage:
        role_prefix = {
            "narrator": "",
            "feifei": "霏霏：",
            "lele": "樂樂：",
            "teacher": "老師：",
        }.get(req.role, "")

        # ---------- 霏霏 ----------
        FEIFEI_SUPPORT_UNCERTAIN = [
            "嗯～事情有時候真的會霧霧的。\n你願意說不確定，代表你有在保護自己。\n我們慢慢來，好嗎？",
            "等等，我剛剛差點忘記記下來。\n你說不確定其實很重要。\n這樣比較安全。",
        ]

        FEIFEI_ACK_OBS = [
            "我聽到你注意到的是：『{obs}』。\n我先幫你放進觀察小口袋。\n之後再一起拿出來看看。",
            "欸對，我剛剛也看到這個！\n『{obs}』先記著，不用急。",
        ]

        FEIFEI_REFLECT = [
            "我們回頭看看用了哪些觀察。\n不是要答對，只是整理一下。\n小腦袋也需要排隊。",
            "等等，我把線索排一下。\n這不是比賽，慢慢來就好。",
        ]

        FEIFEI_SAFE_REDIRECT = [
            "收到你的想法～\n我們先說看到的，不急著貼標籤。\n老師會幫我們一起看。",
            "你願意說出來很勇敢。\n現在先交給老師接住，好嗎？",
        ]

        # ---------- 樂樂 ----------
        LELE_REFLECT = [
            "欸，我剛剛其實有點亂猜。\n現在想想，好像還要再看一下。",
            "我腦袋剛剛轉太快了。\n先慢慢看比較不會撞牆。",
        ]

        # ---------- 老師 ----------
        TEACHER_SAFE = [
            "謝謝你們願意把看到的說出來。\n我們一起再確認，不急。",
        ]

        # ---------- Intent Routing ----------
        if req.intent == "support_uncertain":
            text = random.choice(FEIFEI_SUPPORT_UNCERTAIN)

        elif req.intent == "acknowledge_observation":
            obs = (
                req.selected_observations[0]
                if req.selected_observations
                else req.player_text or "那個小細節"
            )
            text = random.choice(FEIFEI_ACK_OBS).format(obs=obs)

        elif req.intent == "reflect_reasoning":
            # 偶爾換樂樂插話
            if random.random() < 0.3:
                text = random.choice(LELE_REFLECT)
            else:
                text = random.choice(FEIFEI_REFLECT)

        elif req.intent == "safe_redirect_after_accuse":
            if req.role == "teacher":
                text = random.choice(TEACHER_SAFE)
            else:
                text = random.choice(FEIFEI_SAFE_REDIRECT)

        else:
            text = "我們先慢慢來，不急。"

        if role_prefix:
            text = role_prefix + text

        return ResponsePackage(
            intent=req.intent,
            role=req.role,
            text=text.strip(),
        )
