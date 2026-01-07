from .models import GameState
import random


def show_status(state: GameState) -> None:
    p = state.player
    print("-" * 40)
    print(f"回合：{state.turn}")
    print(f"生命：{p.hp}/{p.max_hp} | 金幣：{p.gold}")
    print("-" * 40)


def action_explore(state: GameState) -> None:
    state.turn += 1
    event = random.random()

    if event < 0.5:
        gold = random.randint(1, 5)
        state.player.gold += gold
        print(f"你四處探索，找到 {gold} 枚金幣。")
    else:
        damage = random.randint(1, 4)
        state.player.hp -= damage
        print(f"怪物襲擊你！你受到 {damage} 點傷害。")


def action_rest(state: GameState) -> None:
    state.turn += 1
    heal = random.randint(2, 5)
    state.player.hp = min(state.player.hp + heal, state.player.max_hp)
    print(f"你休息了一下，回復 {heal} 點生命。")


def game_loop() -> None:
    state = GameState()

    print("歡迎來到《QuestForge》！")
    print("請輸入數字選擇行動。")

    while state.player.hp > 0:
        show_status(state)

        print("1) 探索")
        print("2) 休息")
        print("3) 離開遊戲")

        choice = input("> ").strip()

        if choice == "1":
            action_explore(state)
        elif choice == "2":
            action_rest(state)
        elif choice == "3":
            print("冒險者，下次再見。")
            return
        else:
            print("輸入無效，請重新輸入。")

    print("你倒在地城之中……遊戲結束。")
