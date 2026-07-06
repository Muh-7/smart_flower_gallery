# Smart Flower Gallery 🌸🤖

Smart Flower Gallery is a Python planning project that simulates a smart robot responsible for moving flowers from a warehouse to different gallery pavilions.

The robot must choose the best sequence of actions to satisfy the required flower needs while respecting loading and unloading rules. The project uses search algorithms such as **A*** and **DFS** to find and compare possible solutions.

---

## Project Idea

Inside the flower gallery, there is a warehouse that contains different flower baskets.
Each basket can contain flowers of a specific **type** and **color**.

The robot starts from a specific position, moves through the gallery, loads baskets from the warehouse, and unloads them into the correct pavilions.

The goal is to deliver all required flowers with the lowest possible cost.

---

## Main Rules

* The robot can move inside the gallery using grid-based movement.
* The robot can load flower baskets from the warehouse.
* The robot has a limited carrying capacity.
* Each pavilion needs specific flower types and colors.
* Unloading is done using an **all-or-nothing rule**:

  * If the robot has enough flowers to satisfy the full requirement of a specific pavilion/color, it can unload.
  * If the robot does not have enough, it cannot partially unload.
* The robot should find an efficient path that satisfies all needs.

---

## Algorithms Used

### A* Search

A* is used to find an optimized solution by combining:

* `g(n)`: the actual cost from the start state to the current state.
* `h(n)`: the estimated cost from the current state to the goal.
* `f(n) = g(n) + h(n)`: the total priority value.

The heuristic is designed using lower-bound estimates such as:

* Remaining unloading cost.
* Remaining loading cost.
* Movement cost using Manhattan distance.

### DFS

DFS is included as a comparison method.
It explores possible states deeply before backtracking, but it does not guarantee the optimal solution like A* when the heuristic is admissible.

---

## Features

* Smart robot planning system.
* State-space search implementation.
* A* search with heuristic cost estimation.
* DFS comparison.
* Flower type and color requirements.
* Basket generation strategies:

  * Same color across different flower types.
  * Same flower type across different colors.
* Parent tracking to reconstruct the final solution path.
* Optional visualization using Pygame.

---

## Technologies Used

* Python
* Experta
* Pygame
* Heap Queue
* Collections
* Math
* Time

---

## Project Structure

```text
smart-flower-gallery/
│
├── smart_flower.py        # Main project file
├── README.md              # Project documentation
└── requirements.txt       # Project dependencies
```

---

## Installation

```bash
git clone https://github.com/Muh-7/smart-flower-gallery.git
cd smart-flower-gallery
```

```bash
python -m venv venv
source venv/bin/activate
```

```bash
pip install -r requirements.txt
```

If you do not have a `requirements.txt` file yet:

```bash
pip install experta pygame
```

---

## How to Run

```bash
python smart_flower.py
```

The program will start solving the flower delivery problem and print the solution steps.
If visualization is enabled, a Pygame window will show the robot movement during the solving process.

---

## What I Learned

Through this project, I practiced:

* Modeling real-world problems as state-space search problems.
* Designing valid actions and possible states.
* Applying A* search to planning problems.
* Building heuristic functions.
* Comparing informed and uninformed search algorithms.
* Using Python to simulate intelligent decision-making.

---

## Future Improvements

* Add a better graphical interface.
* Add more flower types and colors.
* Support larger gallery maps.
* Improve the heuristic function.
* Add more search algorithms such as BFS, UCS, and Greedy Search.
* Export the final solution path as a report.
* Add unit tests for state transitions and cost calculation.

---

## Author

**Muhammad Kaseem Alsehoum**

AI Department Student
Interested in Artificial Intelligence, Search Algorithms, and Smart Systems.

---

## License

This project is for educational purposes.
