"""Uniform labelled Mealy automata conditioned only on reachable-state count."""
import random

UNIFORM_SAMPLING = 'uniform labelled automata conditioned only on exactly 9 reachable states'


def make_uniform_automaton(module, seed):
    """Preserve the random-call order of the earlier ten-automaton uniform script.

    Each accepted transition table on R has the same probability. The acceptance
    probability depends only on |R| and the alphabet size, so choosing R and q0
    uniformly first also gives uniform sampling over the complete labelled
    automata with a designated initial state and exactly nine reachable states.
    """
    random.seed(seed)
    inputs, outputs = [str(i) for i in range(1, 9)], ['0', '1']
    automaton = module.MealyAutomaton(15, inputs, outputs, self_loop_init=False)
    reachable = sorted(random.sample(range(15), 9))
    outside = [q for q in range(15) if q not in reachable]
    automaton.initial_state = random.choice(reachable)
    while True:
        for q in reachable:
            for symbol in inputs:
                automaton.transitions[q, symbol] = random.choice(reachable)
        if len(automaton.get_reachable_states()) == 9:
            break
    for q in outside:
        for symbol in inputs:
            automaton.transitions[q, symbol] = random.randint(0, 14)
    for q in range(15):
        for symbol in inputs:
            automaton.outputs[q, symbol] = random.choice(outputs)
    return automaton
