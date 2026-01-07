from dataclasses import dataclass, field


@dataclass
class Player:
    name: str = "Hero"
    hp: int = 20
    max_hp: int = 20
    gold: int = 0


@dataclass
class GameState:
    turn: int = 0
    player: Player = field(default_factory=Player)
