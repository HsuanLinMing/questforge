from dataclasses import dataclass, field


@dataclass
class Player:
    """玩家狀態（純資料），適合用 dataclass 表達。

    Flutter 類比：
    - 就像一個簡單的 Model class（不含 UI）
    """
    name: str = "勇者"
    hp: int = 20
    max_hp: int = 20
    gold: int = 0


@dataclass
class GameState:
    """整個遊戲狀態（回合、玩家、之後會加任務/背包/裝備）。

    Flutter 類比：
    - 有點像你在 Provider/Riverpod 裡持有的 State 物件
    """
    turn: int = 0

    # default_factory：每次建立 GameState() 都「新建一個 Player()」
    # 避免 mutable default（所有 GameState 共用同一個 Player 實例）
    # Flutter 類比：player ?? Player()
    player: Player = field(default_factory=Player)
