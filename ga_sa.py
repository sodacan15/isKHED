# ga_sa.py
# Refining stage.
# Step 1: Genetic Algorithm (GA) — 50 iterations of crossover + mutation.
# Step 2: Simulated Annealing (SA) — fine-tunes toward soft constraint satisfaction.

import random
import math
from copy import deepcopy
from data_struct import Professor, Student
from constraint_check import compute_fitness, run_checker
from csp_mcv import time_overlaps


# ─────────────────────────────────────────────────────────
# GENETIC ALGORITHM
# ─────────────────────────────────────────────────────────

GA_POPULATION_SIZE  = 20
GA_GENERATIONS      = 100
GA_MUTATION_RATE    = 0.15
GA_TOURNAMENT_SIZE  = 4


def log_schedule_check(
    label: str,
    schedule: list[dict],
    professors: list[Professor],
    students: list[Student],
    power_outage_schedule: list[str],
) -> dict:
    """Runs a quick validation pass and prints a summary for a stage."""
    result = run_checker(
        schedule=schedule,
        professors=professors,
        students=students,
        power_outage_schedule=power_outage_schedule,
        verbose=False,
    )
    print(
        f"  [{label}] hard={len(result['hard_violations'])} | "
        f"soft={len(result['soft_warnings'])}"
    )
    return result


def initialize_population(
    base_schedule: list[dict],
    domains: dict,
    size: int = GA_POPULATION_SIZE,
) -> list[list[dict]]:
    """
    Creates a population by randomly varying the base schedule.
    Each individual is a full schedule (list of slot dicts).
    """
    population = [base_schedule]
    for _ in range(size - 1):
        individual = []
        for slot in base_schedule:
            course_id = slot["course_id"]
            if course_id in domains and domains[course_id]:
                # Randomly pick from valid domain instead of base slot
                individual.append(random.choice(domains[course_id]))
            else:
                individual.append(deepcopy(slot))
        population.append(individual)
    return population


def tournament_select(
    population: list[list[dict]],
    fitness_scores: list[float],
    k: int = GA_TOURNAMENT_SIZE,
) -> list[dict]:
    """Selects the best individual from a random tournament of k candidates."""
    contestants = random.sample(range(len(population)), k)
    winner = min(contestants, key=lambda i: fitness_scores[i])
    return deepcopy(population[winner])


def crossover(parent1: list[dict], parent2: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Single-point crossover.
    Splits both parents at a random point and swaps tails.
    """
    if len(parent1) != len(parent2) or len(parent1) < 2:
        return deepcopy(parent1), deepcopy(parent2)
    point = random.randint(1, len(parent1) - 1)
    child1 = parent1[:point] + parent2[point:]
    child2 = parent2[:point] + parent1[point:]
    return child1, child2


def repair_schedule(
    individual: list[dict],
    base_schedule: list[dict],
    domains: dict,
) -> list[dict]:
    """
    Ensures each course appears exactly once by keeping the first valid slot
    found for each course_id and filling any missing course_ids from the base
    or domain values.
    """
    course_slots: dict[str, dict] = {}
    for slot in individual:
        course_id = slot["course_id"]
        course_slots.setdefault(course_id, deepcopy(slot))

    # Fill missing courses from the original base schedule if possible.
    for slot in base_schedule:
        course_id = slot["course_id"]
        if course_id not in course_slots and course_id in domains and domains[course_id]:
            course_slots[course_id] = deepcopy(slot)

    # Fallback: use any valid domain value for missing courses.
    for course_id, domain in domains.items():
        if course_id not in course_slots and domain:
            course_slots[course_id] = deepcopy(domain[0])

    # Preserve the original ordering when possible.
    repaired = []
    for slot in base_schedule:
        course_id = slot["course_id"]
        if course_id in course_slots:
            repaired.append(course_slots[course_id])
    for course_id, slot in course_slots.items():
        if slot not in repaired:
            repaired.append(slot)

    return repaired


def mutate(
    individual: list[dict],
    domains: dict,
    mutation_rate: float = GA_MUTATION_RATE,
) -> list[dict]:
    """
    Randomly reassigns a slot to another valid domain value
    with probability = mutation_rate per gene.
    """
    mutated = deepcopy(individual)
    for i, slot in enumerate(mutated):
        if random.random() < mutation_rate:
            course_id = slot["course_id"]
            if course_id in domains and domains[course_id]:
                mutated[i] = random.choice(domains[course_id])
    return mutated


def run_genetic_algorithm(
    base_schedule: list[dict],
    domains: dict,
    professors: list[Professor],
    students: list[Student],
    power_outage_schedule: list[str],
) -> list[dict]:
    """
    Runs GA for GA_GENERATIONS iterations.
    Returns the best schedule found.
    """
    population = initialize_population(base_schedule, domains, GA_POPULATION_SIZE)

    for generation in range(GA_GENERATIONS):
        # Score each individual
        fitness_scores = [
            compute_fitness(ind, professors, students, power_outage_schedule)
            for ind in population
        ]

        best_score = min(fitness_scores)
        print(f"  [GA] Generation {generation + 1}/{GA_GENERATIONS} — best fitness: {best_score}")

        if best_score == 0:
            break  # perfect schedule found early

        # Build next generation
        next_gen = []
        # Elitism: keep the single best individual
        elite_idx = fitness_scores.index(best_score)
        next_gen.append(deepcopy(population[elite_idx]))

        while len(next_gen) < GA_POPULATION_SIZE:
            p1 = tournament_select(population, fitness_scores)
            p2 = tournament_select(population, fitness_scores)
            c1, c2 = crossover(p1, p2)
            c1 = repair_schedule(c1, base_schedule, domains)
            c2 = repair_schedule(c2, base_schedule, domains)
            c1 = mutate(c1, domains)
            c2 = mutate(c2, domains)
            c1 = repair_schedule(c1, base_schedule, domains)
            c2 = repair_schedule(c2, base_schedule, domains)
            next_gen.extend([c1, c2])

        population = next_gen[:GA_POPULATION_SIZE]

    # Return best from final population
    fitness_scores = [
        compute_fitness(ind, professors, students, power_outage_schedule)
        for ind in population
    ]
    best_idx = fitness_scores.index(min(fitness_scores))
    best_schedule = repair_schedule(
        population[best_idx],
        base_schedule,
        domains,
    )
    log_schedule_check(
        "GA final check",
        best_schedule,
        professors,
        students,
        power_outage_schedule,
    )
    print(f"✅ GA done. Best fitness: {fitness_scores[best_idx]}")
    return best_schedule


# ─────────────────────────────────────────────────────────
# SIMULATED ANNEALING
# ─────────────────────────────────────────────────────────

SA_INITIAL_TEMP    = 1000.0
SA_COOLING_RATE    = 0.95
SA_MIN_TEMP        = 1.0
SA_ITERATIONS      = 200    # iterations per temperature step


def get_neighbor(
    schedule: list[dict],
    domains: dict,
) -> list[dict]:
    """
    Generates a neighbor by randomly swapping one slot to another
    valid domain value. This is the SA 'perturbation' step.
    """
    neighbor = deepcopy(schedule)
    idx = random.randint(0, len(neighbor) - 1)
    course_id = neighbor[idx]["course_id"]
    if course_id in domains and len(domains[course_id]) > 1:
        new_slot = random.choice(domains[course_id])
        neighbor[idx] = new_slot
    return neighbor


def run_simulated_annealing(
    ga_schedule: list[dict],
    domains: dict,
    professors: list[Professor],
    students: list[Student],
    power_outage_schedule: list[str],
) -> list[dict]:
    """
    Refines the GA output using Simulated Annealing.
    Accepts worse solutions with decreasing probability as temp cools.
    Focuses on soft constraints (hard violations are already low after GA).
    Returns the best schedule found.
    """
    current   = repair_schedule(deepcopy(ga_schedule), ga_schedule, domains)
    best      = deepcopy(current)
    current_score = compute_fitness(current, professors, students, power_outage_schedule)
    best_score    = current_score
    temp      = SA_INITIAL_TEMP

    step = 0
    while temp > SA_MIN_TEMP:
        for _ in range(SA_ITERATIONS):
            neighbor       = repair_schedule(get_neighbor(current, domains), current, domains)
            neighbor_score = compute_fitness(neighbor, professors, students, power_outage_schedule)
            delta          = neighbor_score - current_score

            # Accept if better, or probabilistically if worse
            if delta < 0 or random.random() < math.exp(-delta / temp):
                current       = neighbor
                current_score = neighbor_score

            if current_score < best_score:
                best       = deepcopy(current)
                best_score = current_score

        temp *= SA_COOLING_RATE
        step += 1
        if step % 10 == 0:
            print(f"  [SA] Temp: {temp:.2f} — best fitness: {best_score}")

        if best_score == 0:
            break  # optimal found

    log_schedule_check(
        "SA final check",
        best,
        professors,
        students,
        power_outage_schedule,
    )
    print(f"✅ SA done. Final best fitness: {best_score}")
    return best


# ─────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────

def refine_schedule(
    base_schedule: list[dict],
    domains: dict,
    professors: list[Professor],
    students: list[Student],
    power_outage_schedule: list[str],
) -> list[dict]:
    """
    Full refinement pipeline:
    1. GA runs for 50 generations to evolve a better schedule.
    2. SA fine-tunes the GA output using soft constraint scoring.

    Returns the final refined schedule.
    """
    print("🧬 Starting Genetic Algorithm...")
    ga_result = run_genetic_algorithm(
        base_schedule, domains, professors, students, power_outage_schedule
    )

    print("🌡️  Starting Simulated Annealing...")
    sa_result = run_simulated_annealing(
        ga_result, domains, professors, students, power_outage_schedule
    )

    return sa_result