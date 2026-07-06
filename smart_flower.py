import contextlib
import heapq
import io
import math
from os import path
import time
import pygame
import collections
import collections.abc
collections.Mapping = collections.abc.Mapping
from collections import namedtuple
from itertools import combinations

from experta import (
    AS,
    MATCH,
    NOT,
    TEST,
    DefFacts,
    Fact,
    Field,
    KnowledgeEngine,
    Rule,
)


PRINT_PATH = True





CATALOG = {
    "rose":   {"red", "pink", "white", "yellow", "maroon"},
    "tulip":  {"red", "yellow", "violet", "orange", "green", "mauve", "purple"},
    "orchid": {"purple", "white", "pink", "rosy"},
    "goliat": {"gold", "light_pink", "yellow"},
}


class Bag:
    

    __slots__ = ("_map", "_items")

    def __init__(self, mapping=None):
        clean = {k: v for k, v in (mapping or {}).items() if v}
        object.__setattr__(self, "_map", clean)
        object.__setattr__(self, "_items", tuple(sorted(clean.items())))

    def get(self, key, default=0):
        return self._map.get(key, default)

    def items(self):
        return self._items

    def total(self):
        return sum(self._map.values())

    def __eq__(self, other):
        return isinstance(other, Bag) and self._items == other._items

    def __hash__(self):
        return hash(self._items)

    def __bool__(self):
        return bool(self._items)

    def __repr__(self):
        if not self._items:
            return "Bag()"
        return "Bag(" + ", ".join(f"{k}:{v}" for k, v in self._items) + ")"


Pavilion = namedtuple("Pavilion", "id type pos")


class World(Fact):
    
    grid = Field(tuple, mandatory=True)          # (w, h)
    warehouse = Field(tuple, mandatory=True)     # (x, y)
    robot_start = Field(tuple, mandatory=True)   # (x, y)
    max_load = Field(int, mandatory=True)
    pavilions = Field(tuple, mandatory=True)     # tuple[Pavilion]


class State(Fact):
    
    pos = Field(tuple, mandatory=True)
    load = Field(Bag, mandatory=True)
    needs = Field(tuple, mandatory=True)         # tuple[Bag], one per pavilion
    g = Field(int, mandatory=True)
    h = Field(int, mandatory=True)
    f = Field(int, mandatory=True)
    op = Field(object, mandatory=True)           # operation that produced this node
    parent = Field(object, mandatory=True)       # parent nid, or None for root
    nid = Field(int, mandatory=True)
    status = Field(str, mandatory=True)          # 'open' / 'current' / 'closed'


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def heuristic(world, pos, load, needs):
    

    # LB_unload: pavilions that still need something.
    lb_unload = sum(1 for need in needs if need)

    # LB_load: pooled (still-needed - usefully-carried) bouquets / max_load.
    total_needed = 0
    total_useful = 0
    for pavilion, need in zip(world["pavilions"], needs):
        for color, qty in need.items():
            total_needed += qty
            total_useful += min(qty, load.get((pavilion.type, color)))
    remaining = total_needed - total_useful
    lb_load = math.ceil(remaining / world["max_load"]) if remaining > 0 else 0

    # LB_move: farthest mandatory point (unmet pavilions, + warehouse if more loads needed).
    mandatory = [p.pos for p, need in zip(world["pavilions"], needs) if need]
    if remaining > 0:
        mandatory.append(world["warehouse"])
    lb_move = max((manhattan(pos, point) for point in mandatory), default=0)

    return lb_unload + lb_load + lb_move


def build_world(instance):
    pavilions = tuple(
        Pavilion(id=pid, type=p["type"], pos=tuple(p["pos"]))
        for pid, p in instance["pavilions"].items()
    )
    max_load = max(sum(p["needs"].values()) for p in instance["pavilions"].values())
    return World(
        grid=(instance["grid"]["w"], instance["grid"]["h"]),
        warehouse=tuple(instance["warehouse"]),
        robot_start=tuple(instance["robot_start"]),
        max_load=max_load,
        pavilions=pavilions,
    )


def build_root_state(instance, world):
    needs = tuple(Bag(p["needs"]) for p in instance["pavilions"].values())
    load = Bag()
    pos = tuple(instance["robot_start"])
    h = heuristic(world, pos, load, needs)
    return State(
        pos=pos, load=load, needs=needs,
        g=0, h=h, f=h,
        op="start", parent=None, nid=0, status="open",
    )



# operators.py -- Mechanical helpers for the successor-generator rules


def candidate_baskets(pavilions, needs, max_load):
    
    demand = {}
    for pavilion, need in zip(pavilions, needs):
        for color, qty in need.items():
            key = (pavilion.type, color)
            demand[key] = demand.get(key, 0) + qty

    baskets = set()

    
    by_type = {}
    for (ptype, color), qty in demand.items():
        by_type.setdefault(ptype, []).append((color, qty))
    for ptype, colors in by_type.items():
        for r in range(1, len(colors) + 1):
            for combo in combinations(colors, r):
                if sum(q for _, q in combo) <= max_load:
                    baskets.add(Bag({(ptype, c): q for c, q in combo}))

    
    by_color = {}
    for (ptype, color), qty in demand.items():
        by_color.setdefault(color, []).append((ptype, qty))
    for color, types in by_color.items():
        if len(types) < 2:
            continue
        for r in range(2, len(types) + 1):
            for combo in combinations(types, r):
                if sum(q for _, q in combo) <= max_load:
                    baskets.add(Bag({(t, color): q for t, q in combo}))

    return baskets


def deliverable_colors(pavilion_type, load, need):
    """Colors of `need` that `load` carries enough of to fully satisfy."""
    return [color for color, qty in need.items() if load.get((pavilion_type, color)) >= qty]


def apply_unload(pavilion_type, load, need):
    """Drop every deliverable color; return (new_load, new_need), or None if nothing to drop."""
    colors = deliverable_colors(pavilion_type, load, need)
    if not colors:
        return None
    new_load = dict(load.items())
    new_need = dict(need.items())
    for color in colors:
        qty = new_need.pop(color)
        key = (pavilion_type, color)
        remaining = new_load[key] - qty
        if remaining:
            new_load[key] = remaining
        else:
            del new_load[key]
    return Bag(new_load), Bag(new_need)



# engine.py -- Shared SearchEngine base: bookkeeping + child-spawning


class SearchEngine(KnowledgeEngine):
    """Shared bookkeeping: instance setup, child-spawning, path reconstruction."""

    def __init__(self, instance):
        super().__init__()
        self.instance = instance
        self.goal = None  # populated by print_solution() when goal_check fires

    @DefFacts()
    def _initial_facts(self):
        self.world = build_world(self.instance)
        root = build_root_state(self.instance, self.world)
        self.seen = {(root["pos"], root["load"], root["needs"]): root["g"]}
        self.nodes = {root["nid"]: root}
        self._next_nid = 1
        self.open_heap = [(root["f"], root["nid"])]
        yield self.world
        yield root

    def next_nid(self):
        nid = self._next_nid
        self._next_nid += 1
        return nid

    def spawn(self, parent, op, pos=None, load=None, needs=None):
        pos = parent["pos"] if pos is None else pos
        load = parent["load"] if load is None else load
        needs = parent["needs"] if needs is None else needs
        g = parent["g"] + 1

        gw, gh = self.world["grid"]
        if not (1 <= pos[0] <= gw and 1 <= pos[1] <= gh):
            return None

        key = (pos, load, needs)
        if key in self.seen and self.seen[key] <= g:
            return None
        self.seen[key] = g

        h = heuristic(self.world, pos, load, needs)
        child = State(
            pos=pos, load=load, needs=needs,
            g=g, h=h, f=g + h,
            op=op, parent=parent["nid"], nid=self.next_nid(), status="open",
        )
        self.nodes[child["nid"]] = child
        self.declare(child)
        heapq.heappush(self.open_heap, (child["f"], child["nid"]))
        print("  " * child["g"] + repr(child))
        return child

    # -- goal + path

    def reconstruct_path(self, goal):
        path = []
        node = goal
        while node is not None:
            path.append(node)
            node = self.nodes.get(node["parent"])
        path.reverse()
        return path

    def print_solution(self, goal):
        self.goal = goal  
        path = self.reconstruct_path(goal)
        ops = [node["op"] for node in path[1:]]
        print("Solution:", " -> ".join(ops))
        print("Cost:", goal["g"])

    def print_solution_path(self):

        if self.goal is None:
            return
        path = self.reconstruct_path(self.goal)
        pavilions = self.world["pavilions"]
        print(f"=== Path ({len(path) - 1} steps, cost {self.goal['g']}) ===")
        for step, node in enumerate(path):
            print(
                f"Step {step:>2} [{node['op']:<11}] "
                f"pos={node['pos']}  load={node['load']}  "
                f"g={node['g']} h={node['h']} f={node['f']}"
            )
            needs_str = "  ".join(
                f"{p.id}={n}" for p, n in zip(pavilions, node["needs"])
            )
            print(f"             needs: {needs_str}")
        print()



# engine.py -- FlowerEngine: depth-first search


class FlowerEngine(SearchEngine):
    
    @Rule(
        AS.goal << State(needs=MATCH.needs, load=MATCH.load, status="open"),
        TEST(lambda needs, load: not load and all(not n for n in needs)),
        salience=30,
    )
    def goal_check(self, goal, needs, load):
        self.print_solution(goal)
        self.halt()

    # -- successor generators ------------------------------------------------

    @Rule(
        World(grid=MATCH.grid),
        AS.parent << State(pos=MATCH.pos, status="open"),
        TEST(lambda pos, grid: pos[0] < grid[0]),
    )
    def move_right(self, parent, pos, grid):
        x, y = pos
        self.spawn(parent, "move_right", pos=(x + 1, y))
        
        

    @Rule(
        AS.parent << State(pos=MATCH.pos, status="open"),
        TEST(lambda pos: pos[0] > 1),
    )
    def move_left(self, parent, pos):
        x, y = pos
        self.spawn(parent, "move_left", pos=(x - 1, y))

    @Rule(
        World(grid=MATCH.grid),
        AS.parent << State(pos=MATCH.pos, status="open"),
        TEST(lambda pos, grid: pos[1] < grid[1]),
    )
    def move_up(self, parent, pos, grid):
        x, y = pos
        self.spawn(parent, "move_up", pos=(x, y + 1))

    @Rule(
        AS.parent << State(pos=MATCH.pos, status="open"),
        TEST(lambda pos: pos[1] > 1),
    )
    def move_down(self, parent, pos):
        x, y = pos
        self.spawn(parent, "move_down", pos=(x, y - 1))

    @Rule(
        World(warehouse=MATCH.warehouse, max_load=MATCH.max_load, pavilions=MATCH.pavilions),
        AS.parent << State(pos=MATCH.pos, load=MATCH.load, needs=MATCH.needs, status="open"),
        TEST(lambda pos, warehouse: pos == warehouse),
        TEST(lambda load: not load),
    )
    def load(self, parent, pos, load, needs, warehouse, max_load, pavilions):
        for basket in candidate_baskets(pavilions, needs, max_load):
            self.spawn(parent, "load", load=basket)

    @Rule(
        World(pavilions=MATCH.pavilions),
        AS.parent << State(pos=MATCH.pos, load=MATCH.load, needs=MATCH.needs, status="open"),
    )
    def unload(self, parent, pos, load, needs, pavilions):
        for idx, pavilion in enumerate(pavilions):
            if pavilion.pos != pos or not needs[idx]:
                continue
            result = apply_unload(pavilion.type, load, needs[idx])
            if result is None:
                continue
            new_load, new_need = result
            new_needs = needs[:idx] + (new_need,) + needs[idx + 1:]
            self.spawn(parent, "unload", load=new_load, needs=new_needs)




class AStarEngine(SearchEngine):

    @Rule(
        AS.f << State(nid=0, status="open"),
        salience=100,
    )
    def bootstrap(self, f):
        self.nodes[0] = f

    @Rule(
        AS.goal << State(needs=MATCH.needs, load=MATCH.load, status="current"),
        TEST(lambda needs, load: not load and all(not n for n in needs)),
        salience=30,
    )
    def goal_check(self, goal, needs, load):
        self.print_solution(goal)
        self.halt()

    # -- successor generators (expand the 'current' state) -------------------

    @Rule(
        World(grid=MATCH.grid),
        AS.parent << State(pos=MATCH.pos, status="current"),
        TEST(lambda pos, grid: pos[0] < grid[0]),
        salience=20,
    )
    def move_right(self, parent, pos, grid):
        x, y = pos
        self.spawn(parent, "move_right", pos=(x + 1, y))

    @Rule(
        AS.parent << State(pos=MATCH.pos, status="current"),
        TEST(lambda pos: pos[0] > 1),
        salience=20,
    )
    def move_left(self, parent, pos):
        x, y = pos
        self.spawn(parent, "move_left", pos=(x - 1, y))

    @Rule(
        World(grid=MATCH.grid),
        AS.parent << State(pos=MATCH.pos, status="current"),
        TEST(lambda pos, grid: pos[1] < grid[1]),
        salience=20,
    )
    def move_up(self, parent, pos, grid):
        x, y = pos
        self.spawn(parent, "move_up", pos=(x, y + 1))

    @Rule(
        AS.parent << State(pos=MATCH.pos, status="current"),
        TEST(lambda pos: pos[1] > 1),
        salience=20,
    )
    def move_down(self, parent, pos):
        x, y = pos
        self.spawn(parent, "move_down", pos=(x, y - 1))

    @Rule(
        World(warehouse=MATCH.warehouse, max_load=MATCH.max_load, pavilions=MATCH.pavilions),
        AS.parent << State(pos=MATCH.pos, load=MATCH.load, needs=MATCH.needs, status="current"),
        TEST(lambda pos, warehouse: pos == warehouse),
        TEST(lambda load: not load),
        salience=20,
    )
    def load(self, parent, pos, load, needs, warehouse, max_load, pavilions):
        for basket in candidate_baskets(pavilions, needs, max_load):
            self.spawn(parent, "load", load=basket)

    @Rule(
        World(pavilions=MATCH.pavilions),
        AS.parent << State(pos=MATCH.pos, load=MATCH.load, needs=MATCH.needs, status="current"),
        salience=20,
    )
    def unload(self, parent, pos, load, needs, pavilions):
        for idx, pavilion in enumerate(pavilions):
            if pavilion.pos != pos or not needs[idx]:
                continue
            result = apply_unload(pavilion.type, load, needs[idx])
            if result is None:
                continue
            new_load, new_need = result
            new_needs = needs[:idx] + (new_need,) + needs[idx + 1:]
            self.spawn(parent, "unload", load=new_load, needs=new_needs)


    @Rule(
        AS.cur << State(status="current"),
        salience=10,
    )
    def close_current(self, cur):
        self.modify(cur, status="closed")

    @Rule(
        NOT(State(status="current")),
        salience=0,
    )
    def select_best(self):
        if not self.open_heap:
            return
        _, nid = heapq.heappop(self.open_heap)
        self.modify(self.nodes[nid], status="current")



EXAMPLE_A = {
    "grid": {"w": 3, "h": 3},
    "warehouse": (2, 2),
    "robot_start": (1, 1),
    "pavilions": {
        "P1": {"type": "rose", "pos": (3, 3), "needs": {"red": 1, "pink": 1}},
    },
    "expected": {"astar_cost": 6},
}

EXAMPLE_B = {
    "grid": {"w": 5, "h": 5},
    "warehouse": (2, 2),
    "robot_start": (2, 2),
    "pavilions": {
        "P1": {"type": "rose",   "pos": (2, 3), "needs": {"red": 2, "pink": 2}},
        "P2": {"type": "tulip",  "pos": (3, 2), "needs": {"yellow": 2}},
        "P3": {"type": "goliat", "pos": (4, 2), "needs": {"yellow": 2}},
    },
    "expected": {"astar_cost": 9},
}

NO_SHARED_COLOR = {
    "grid": {"w": 3, "h": 3},
    "warehouse": (2, 2),
    "robot_start": (2, 2),
    "pavilions": {
        "P1": {"type": "rose",  "pos": (1, 2), "needs": {"red": 1}},
        "P2": {"type": "tulip", "pos": (3, 2), "needs": {"green": 1}},
    },
    "expected": {"astar_cost": 7},
}

ASSIGNMENT_EXAMPLE = {
    "grid": {"w": 5, "h": 5},
    "warehouse": (3, 2),
    "robot_start": (3, 1),
    "pavilions": {
        "P1": {"type": "rose",   "pos": (2, 4), "needs": {"red": 2, "pink": 1, "white": 1}},
        "P2": {"type": "tulip",  "pos": (4, 3), "needs": {"red": 3, "yellow": 1}},
        "P3": {"type": "orchid", "pos": (4, 5), "needs": {"purple": 2, "pink": 1}},
        "P4": {"type": "goliat", "pos": (5, 2), "needs": {"gold": 2, "light_pink": 2}},
    },
}



def run(engine_cls, instance, label):
    engine = engine_cls(instance)
    engine.reset()
    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        engine.run()
    elapsed = time.time() - t0

    lines = buf.getvalue().splitlines()
    nodes_expanded = len(lines) - 2  # all lines except "Solution:"/"Cost:"
    cost = int([l for l in lines if l.startswith("Cost")][0].split(":")[1])

    print(f"--- {label} ---")
    print(f"Cost: {cost}  (nodes expanded: {nodes_expanded}, {elapsed:.2f}s)")
    if PRINT_PATH:
        engine.print_solution_path()
    else:
        print()
    return engine, cost

CELL_SIZE = 100

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

GREEN = (0, 180, 0)
RED = (220, 0, 0)
BLUE = (0, 100, 255)
YELLOW = (255, 200, 0)
GRAY = (180, 180, 180)


def visualize_solution(world, path):

    pygame.init()

    grid_w, grid_h = world["grid"]

    INFO_WIDTH = 400

    screen = pygame.display.set_mode(
        (
            grid_w * CELL_SIZE + INFO_WIDTH,
            grid_h * CELL_SIZE
        )
    )

    pygame.display.set_caption("Flower Robot Visualization")

    font = pygame.font.SysFont(None, 28)
    small_font = pygame.font.SysFont(None, 22)

    step = 0
    clock = pygame.time.Clock()

    running = True

    while running:

        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                running = False

        screen.fill(WHITE)

        node = path[min(step, len(path) - 1)]

        # ==================================================
        # GRID
        # ==================================================

        for x in range(grid_w):
            for y in range(grid_h):

                rect = pygame.Rect(
                    x * CELL_SIZE,
                    (grid_h - 1 - y) * CELL_SIZE,
                    CELL_SIZE,
                    CELL_SIZE
                )

                pygame.draw.rect(screen, BLACK, rect, 1)

        # ==================================================
        # WAREHOUSE
        # ==================================================

        wx, wy = world["warehouse"]

        pygame.draw.rect(
            screen,
            GREEN,
            (
                (wx - 1) * CELL_SIZE,
                (grid_h - wy) * CELL_SIZE,
                CELL_SIZE,
                CELL_SIZE
            )
        )

        warehouse_text = font.render("W", True, WHITE)

        screen.blit(
            warehouse_text,
            (
                (wx - 1) * CELL_SIZE + 40,
                (grid_h - wy) * CELL_SIZE + 35
            )
        )

        # ==================================================
        # PAVILIONS
        # ==================================================

        current_needs = node["needs"]

        for pavilion, need in zip(
                world["pavilions"],
                current_needs
        ):

            px, py = pavilion.pos

            color = RED

            if not need:
                color = GRAY

            pygame.draw.rect(
                screen,
                color,
                (
                    (px - 1) * CELL_SIZE,
                    (grid_h - py) * CELL_SIZE,
                    CELL_SIZE,
                    CELL_SIZE
                )
            )

            text = font.render(
                pavilion.id,
                True,
                WHITE
            )

            screen.blit(
                text,
                (
                    (px - 1) * CELL_SIZE + 15,
                    (grid_h - py) * CELL_SIZE + 35
                )
            )

        # ==================================================
        # ROBOT
        # ==================================================

        robot_color = BLUE

        if node["op"] == "load":
            robot_color = YELLOW

        elif node["op"] == "unload":
            robot_color = GREEN

        rx, ry = node["pos"]

        pygame.draw.circle(
            screen,
            robot_color,
            (
                (rx - 1) * CELL_SIZE + CELL_SIZE // 2,
                (grid_h - ry) * CELL_SIZE + CELL_SIZE // 2
            ),  
            30
        )

        # ==================================================
        # SIDE PANEL
        # ==================================================

        panel_x = grid_w * CELL_SIZE + 10

        y = 20

        title = font.render(
            f"Step {step}",
            True,
            BLACK
        )

        screen.blit(title, (panel_x, y))

        y += 50

        op_text = font.render(
            f"Operation: {node['op']}",
            True,
            BLACK
        )

        screen.blit(op_text, (panel_x, y))

        y += 50

        ghf = font.render(
            f"g={node['g']}  h={node['h']}  f={node['f']}",
            True,
            BLACK
        )

        screen.blit(ghf, (panel_x, y))

        y += 60

        load_title = font.render(
            "Robot Load",
            True,
            BLACK
        )

        screen.blit(load_title, (panel_x, y))

        y += 35

        if node["load"]:

            for flower, qty in node["load"].items():

                txt = small_font.render(
                    f"{flower}: {qty}",
                    True,
                    BLACK
                )

                screen.blit(txt, (panel_x, y))

                y += 25

        else:

            txt = small_font.render(
                "Empty",
                True,
                BLACK
            )

            screen.blit(txt, (panel_x, y))

            y += 30

        y += 20

        needs_title = font.render(
            "Remaining Needs",
            True,
            BLACK
        )

        screen.blit(needs_title, (panel_x, y))

        y += 35

        for pavilion, need in zip(
                world["pavilions"],
                current_needs
        ):

            txt = small_font.render(
                f"{pavilion.id}: {need}",
                True,
                BLACK
            )

            screen.blit(txt, (panel_x, y))

            y += 25

        pygame.display.flip()

        if step < len(path) - 1:

            pygame.time.wait(700)

            step += 1

        clock.tick(60)

    pygame.quit()
    
    
def main():
    run(AStarEngine, EXAMPLE_B, "A* / Example B (expect optimal cost 9)")

    astar_engine, astar_cost = run(AStarEngine, ASSIGNMENT_EXAMPLE, "A* / 4-pavilion assignment example")
    path = astar_engine.reconstruct_path(
    astar_engine.goal)

    visualize_solution(
        astar_engine.world,
        path)
    
    dfs_engine, dfs_cost = run(
        FlowerEngine,
        ASSIGNMENT_EXAMPLE,
        "DFS / 4-pavilion assignment example"
                                )

    print(f"A* <= DFS? {astar_cost} <= {dfs_cost}: {astar_cost <= dfs_cost}\n")

    run(AStarEngine, NO_SHARED_COLOR, "A* / no-shared-color instance (expect optimal cost 7)")
    run(FlowerEngine, NO_SHARED_COLOR, "DFS / no-shared-color instance (expect cost >= 7)")


if __name__ == "__main__":
    main()
