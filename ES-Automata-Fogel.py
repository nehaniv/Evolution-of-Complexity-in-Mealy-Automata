# Set Up and Automata Clases
import argparse
import random
import datetime
import copy
import subprocess
import matplotlib.pyplot as plt
import graphviz
import numpy as np
import re
import pandas as pd
import multiprocessing as mp
import os 

# ----------------- Configuration -----------------
DEFAULT_INPUT_ALPHABET = ['0', '1']
DEFAULT_OUTPUT_ALPHABET = ['0', '1']

# ----------------- Automaton Class -----------------
class MealyAutomaton:
    def __init__(self, num_states, input_alphabet, output_alphabet, self_loop_init=False ):
        self.num_states = num_states
        self.input_alphabet = input_alphabet
        self.output_alphabet = output_alphabet
        self.initial_state = random.randint(0, num_states - 1)

        if self_loop_init:
            self.transitions = {
                (state, inp): state
                for state in range(num_states)
                for inp in input_alphabet
            }
        else:
            self.transitions = {
                (state, inp): random.randint(0, num_states - 1)
                for state in range(num_states)
                for inp in input_alphabet
            }

        self.outputs = {
            (state, inp): random.choice(output_alphabet)
            for state in range(num_states)
            for inp in input_alphabet
        }

### Apply 1, 2, or 3 mutations according to probability weights
    def mutate(self):
        num_mutations = random.choices(
            [1, 2, 3],
            weights=[0.65, 0.25, 0.1],
            k=1
        )[0]

        for _ in range(num_mutations):
            mutation_type = random.choice(['transition', 'output', 'initial', 'merge_state'])
        
            if mutation_type == 'transition': 
                key = random.choice(list(self.transitions.keys()))
                self.transitions[key] = random.randint(0, self.num_states - 1)
                
            elif mutation_type == 'output':
                key = random.choice(list(self.outputs.keys()))
                self.outputs[key] = random.choice(self.output_alphabet)
                
            elif mutation_type == 'initial':
                self.initial_state = random.randint(0, self.num_states - 1)
                
            elif mutation_type == 'merge_state':
                state_a, state_b = random.sample(range(self.num_states), 2)
                for (src_state, inp), target_state in self.transitions.items():
                    if target_state == state_b: 
                        self.transitions[(src_state, inp)] = state_a


### OLD Single Mutation
#    def mutate(self):
#        mutation_type = random.choice(['transition', 'output', 'initial', 'merge_state'])
#    #   mutation_type = random.choice(['transition', 'output', 'initial'])
#        if mutation_type == 'transition':
#            key = random.choice(list(self.transitions.keys()))
#            self.transitions[key] = random.randint(0, self.num_states - 1)
#        elif mutation_type == 'output':
#            key = random.choice(list(self.outputs.keys()))
#            self.outputs[key] = random.choice(self.output_alphabet)
#        elif mutation_type == 'initial':
#            self.initial_state = random.randint(0, self.num_states - 1)
#        elif mutation_type == 'merge_state':
#            state_a, state_b = random.sample(range(self.num_states), 2)
#            for (src_state, inp), target_state in self.transitions.items():
#                if target_state == state_b:
#                    self.transitions[(src_state, inp)] = state_a

    def predict_stepwise(self, input_sequence):
        state = self.initial_state
        pairs = []
        for symbol in input_sequence:
            output = self.outputs[(state, symbol)]
            pairs.append((symbol, output))
            state = self.transitions[(state, symbol)]
        return pairs

    def get_reachable_states(self):
        reachable = set()
        queue = [self.initial_state]
        while queue:
            state = queue.pop()
            if state not in reachable:
                reachable.add(state)
                for symbol in self.input_alphabet:
                    next_state = self.transitions[(state, symbol)]
                    queue.append(next_state)
        return sorted(reachable)

    def clone(self):
        return copy.deepcopy(self)

    def to_dot(self, reachable_only=False):
        reachable = set(self.get_reachable_states())
        dot = graphviz.Digraph(format='pdf')
    
        # ➔ Add the invisible "start" node and arrow to initial state
        dot.node('start', shape='point')
        dot.edge('start', str(self.initial_state))

        for state in range(self.num_states):
            if reachable_only and state not in reachable:
                continue
            shape = 'circle'
            #  If the state is not reachable, make it dotted
            style = 'solid' if state in reachable else 'dotted'
            dot.node(str(state), shape=shape, style=style)

        for (state, inp), next_state in self.transitions.items():
            if reachable_only and (state not in reachable or next_state not in reachable):
                continue
            label = f"{inp}/{self.outputs[(state, inp)]}"
            dot.edge(str(state), str(next_state), label=label)

        return dot


#    def to_dot(self, reachable_only=False):
#        reachable = set(self.get_reachable_states()) if reachable_only else None
#        dot = graphviz.Digraph(format='pdf')
#        for state in range(self.num_states):
#            if reachable_only and state not in reachable:
#                continue
#            shape = 'circle'
#            if state == self.initial_state:
#                shape = 'doublecircle'
#            style = 'solid' if state in reachable else 'dotted'
#            dot.node(str(state), shape=shape, style=style)
#        for (state, inp), next_state in self.transitions.items():
#            if reachable_only and (state not in reachable or next_state not in reachable):
#                continue
#            label = f"{inp}/{self.outputs[(state, inp)]}"
#            dot.edge(str(state), str(next_state), label=label)
#        return dot

# Part 2: Environment DFA and Fitness Functions

# ----------------- Environment DFA -----------------
class EnvironmentDFA:
    def __init__(self, num_states, input_alphabet, variant='SimpleHardestEnvironment'):
        self.num_states = num_states
        self.input_alphabet = input_alphabet
        self.variant = variant
        self.initial_state = 0
        self.transitions = {}
        for state in range(num_states):
            for symbol in input_alphabet:
                if variant == 'SimpleEasiestEnvironment':
                    if symbol == '0':
                        self.transitions[(state, symbol)] = state
                    elif symbol == '1':
                        self.transitions[(state, symbol)] = (state + 1) % num_states
                elif variant == 'SimpleHardestEnvironment':
                    if symbol == '0':
                        self.transitions[(state, symbol)] = 0
                    elif symbol == '1':
                        self.transitions[(state, symbol)] = (state + 1) % num_states

# ----------------- Fitness Functions -----------------
def eightball_fitness(automaton, target):
    raw_pairs = automaton.predict_stepwise(target[:-1])  # feed up to second-last
    seen = set()
    pairs = []
    for (inp, out) in raw_pairs:
        pair = (inp, out)
        first_time = pair not in seen
        if first_time:
            seen.add(pair)
        pairs.append((pair, first_time))
    
    # Compare automaton outputs vs next target input
    match = sum(1 for (pair, _), expected in zip(pairs, target[1:]) if pair[1] == expected)

    penalty = len(automaton.get_reachable_states())
    return match - penalty, pairs

def fogel_palindrome_fitness(automaton, target):
    raw_pairs = automaton.predict_stepwise(target[:-1])  # feed up to second-last
    seen = set()
    pairs = []
    for (inp, out) in raw_pairs:
        pair = (inp, out)
        first_time = pair not in seen
        if first_time:
            seen.add(pair)
        pairs.append((pair, first_time))
    
    # Compare automaton outputs vs next target input
    match = sum(1 for (pair, _), expected in zip(pairs, target[1:]) if pair[1] == expected)

    penalty = len(automaton.get_reachable_states())
    return match - penalty, pairs

def traversal_fitness(automaton, env_dfa):
    visited = set()
    env_state = env_dfa.initial_state
    mealy_state = automaton.initial_state
    pairs = []
    seen_pairs = set()
    for _ in range(100):
        env_input = str(env_state + 1)
        if env_input not in automaton.input_alphabet:
            continue
        mealy_output = automaton.outputs.get((mealy_state, env_input))
        mealy_state = automaton.transitions.get((mealy_state, env_input), mealy_state)
        if mealy_output in env_dfa.input_alphabet:
            visited.add((env_state, mealy_output))
            env_state = env_dfa.transitions.get((env_state, mealy_output), env_state)
        pair = (env_input, mealy_output)
        first_time = pair not in seen_pairs
        if first_time:
            seen_pairs.add(pair)
        pairs.append((pair, first_time))  # ensure structured ((inp, out), first_time)
    penalty = 0.1 * len(automaton.get_reachable_states())
#    penalty = 0.05 * len(automaton.get_reachable_states()) # Reduced penalty to half

    return len(visited) - penalty, pairs

def multitraversal_fitness(automaton, env_dfa):
    total_fitness = 0
    all_pairs = []
    per_start_results = []
    for start in range(env_dfa.num_states):
        visited = set()
        env_state = start
        mealy_state = automaton.initial_state
        pairs = []
        seen_pairs = set()
        for _ in range(100):
            env_input = str(env_state + 1)
            if env_input not in automaton.input_alphabet:
                continue
            mealy_output = automaton.outputs.get((mealy_state, env_input))
            mealy_state = automaton.transitions.get((mealy_state, env_input), mealy_state)
            if mealy_output in env_dfa.input_alphabet:
                visited.add((env_state, mealy_output))
                env_state = env_dfa.transitions.get((env_state, mealy_output), env_state)
            pair = (env_input, mealy_output)
            first_time = pair not in seen_pairs
            if first_time:
                seen_pairs.add(pair)
            pairs.append((pair, first_time))
        fitness = len(visited)
        total_fitness += fitness 
        result = {
            "start_state": start,
            "run_fitness": fitness,
            "pairs": pairs
        }
        if start == env_dfa.num_states - 1:
            penalty = 0.8 * len(automaton.get_reachable_states())
            result["fitness"] = total_fitness - penalty
            total_fitness = result["fitness"]
        per_start_results.append(result)
        all_pairs.extend(pairs)
    return total_fitness, {"per_start": per_start_results, "all_pairs": all_pairs, "total_fitness": total_fitness, "penalty": penalty}

FITNESS_FUNCTIONS = {
    "EightBall": eightball_fitness,
    "FogelPalindrome": fogel_palindrome_fitness,
    "Traversal": traversal_fitness,
    "MultiTraversal": multitraversal_fitness,
}




# Part 3: Evolution Strategy, Plotting, GAP Saving, LaTeX Report, Main
# ----------------- Evolution Strategy -----------------
def evolution_strategy(population, runs, generations, offspring_size,
                       fitness_name, env_variant, timestamp):

    # Set input sequence and input alphabet depending on fitness
    if fitness_name == "EightBall":
        input_seq = ('00011000' * 12)[:84]
    elif fitness_name == "FogelPalindrome":
        input_seq = ('101110011101' * 10)
    elif fitness_name in ["Traversal", "MultiTraversal"]:
        input_seq = ""  # Traversal doesn't use a fixed sequence
    else:
        raise ValueError(f"Unknown fitness function: {fitness_name}")

    # Environment DFA is only needed for Traversal and MultiTraversal
    env_dfa = EnvironmentDFA(8, ['0', '1'], variant=env_variant) if fitness_name in ["Traversal", "MultiTraversal"] else None

    # Fitness function setup
    if fitness_name == "Traversal":
        fitness_fn = lambda a: traversal_fitness(a, env_dfa)
    elif fitness_name == "MultiTraversal":
        fitness_fn = lambda a: multitraversal_fitness(a, env_dfa)
    else:
        fitness_fn = lambda a: FITNESS_FUNCTIONS[fitness_name](a, input_seq)

    all_run_data = []
    best_per_run = []

    for run in range(runs):
        print(f" Run {run + 1}/{runs}")
        random.seed(run)

        # Copy initial population so each run starts from the same base
        pop = [copy.deepcopy(ind) for ind in population]

        run_data = {"max": [], "avg": [], "reachable": []}
        for gen in range(generations):
            offspring = [random.choice(pop).clone() for _ in range(offspring_size)]

            for ind in offspring:
                ind.mutate()

            # Combine current population and offspring, tagging each:
            combined = [(ind, 0) for ind in pop] + [(ind, 1) for ind in offspring]

            # Compute fitness scores
            fitness_scores = [fitness_fn(ind)[0] for ind, _ in combined]

            # Sort: first by fitness, then by priority (offspring=1)
            sorted_combined = [
                ind for (_, (ind, priority)) in sorted(
                    zip(fitness_scores, combined),
                    key=lambda pair: (pair[0], pair[1][1]),  # (fitness, priority)
                    reverse=True
                )
            ]

            # Select top N
            pop = sorted_combined[:len(pop)]

            fitness_scores = [fitness_fn(ind)[0] for ind in pop]
            best_idx = max(range(len(fitness_scores)), key=lambda i: fitness_scores[i])
            best = fitness_scores[best_idx]
            avg = sum(fitness_scores) / len(pop)
            avg_reachable = np.mean([len(ind.get_reachable_states()) for ind in pop])
            run_data["max"].append(best)
            run_data["avg"].append(avg)
            run_data["reachable"].append(avg_reachable)

        # Print best of run score while running
        print("Fitness: ", best, "\n");

        # Save best automaton of this run
        best_run_automaton = pop[best_idx].clone()
        best_pairs = fitness_fn(best_run_automaton)[1]
        best_per_run.append((best_run_automaton, fitness_scores[best_idx], best_pairs, run_data))

        # Generate DOT and GAP files
        dot = best_run_automaton.to_dot()
        dot.render(filename=f'best_automaton_run_{run + 1}_{timestamp}', format='pdf', cleanup=False)

        dot_reachable = best_run_automaton.to_dot(reachable_only=True)
        dot_reachable.render(filename=f'best_automaton_run_{run + 1}_{timestamp}_reachable', format='pdf', cleanup=False)

        save_gap_file(best_run_automaton, run + 1, timestamp, reachable_only=False)
        save_gap_file(best_run_automaton, run + 1, timestamp, reachable_only=True)

        all_run_data.append(run_data)

        # Find best overall automaton from all runs
        best_overall = max(best_per_run, key=lambda x: x[1])  # returns the (automaton, fitness, ...)

    return all_run_data, best_overall, best_per_run



# ----------------- GAP File Saver -----------------
def save_gap_file(automaton, run_number, timestamp, reachable_only):
    suffix = "_reachable.g" if reachable_only else ".g"
    filename = f"best_automaton_run_{run_number}_{timestamp}{suffix}"
    states = automaton.get_reachable_states() if reachable_only else range(automaton.num_states)
    state_map = {old: i + 1 for i, old in enumerate(states)}  # 1-indexed

    with open(filename, 'w') as gf:
        if len(states) == 1:
            gf.write('Print("number of reachable states: 1\\n");\n')
            gf.write('Print("complexity upper bound:0\\n");\n')
            gf.write('Print("non-aperiodic:0\\n");\n')
            gf.write(
                'Print("\\nMax Chain of Essential Dependencies: '
                'Maximum Chain Found:\\n\\n");\n'
            )
            return

        for inp in automaton.input_alphabet:
            next_states = [state_map[automaton.transitions[(s, inp)]] for s in states]
            outputs = [int(automaton.outputs[(s, inp)]) for s in states]
            gf.write(f"NextState{inp} := Transformation([{', '.join(map(str, next_states))}]);\n")
#            gf.write(f"# Output{inp} := Transformation([{', '.join(map(str, outputs))}]);\n")
            gf.write(f"# Output{inp} := [{', '.join(map(str, outputs))}];\n")
        gf.write(f"\nS_gen := [{', '.join([f'NextState{inp}' for inp in automaton.input_alphabet])}];\n")
        gf.write("S := Semigroup(S_gen); sk := Skeleton(S);\n")
        gf.write("Print(\"number of reachable states: \",Size(BaseSet(sk)),\"\\n\");\n");
        gf.write("cpxbound := 0;") 
        gf.write("for dx in [1..DepthOfSkeleton(sk)-1] \n do no_holonomy_group_seen_yet_at_this_level := true; \n for  x1 in RepresentativeSets(sk)[dx] \n do px1 := PermutatorGroup(sk,x1); hx1 := HolonomyGroup@SgpDec(sk,x1); \n if IsTrivial(hx1)  then trivialgroup := true; \n  else  if no_holonomy_group_seen_yet_at_this_level then cpxbound := cpxbound + 1; \n  no_holonomy_group_seen_yet_at_this_level := false; fi;\n  fi;\n  od; \n od; \n Print(\"complexity upper bound:\",cpxbound,\"\\n\"); \n Print(\"non-aperiodic:\", Minimum([cpxbound,1]),\"\\n\"); \n  ")
        gf.write("DisplayHolonomyComponents(sk); \n Print(\"\\n  Max Chain of Essential Dependencies: \"); \n  MaxChainOfEssentialDependency(sk);\n\n\n")
#SUPPRESS MAX CHAIN command:  
       # gf.write("DisplayHolonomyComponents(sk); \n Print(\"\\n  Max Chain of Essential Dependencies: \"); \n #  MaxChainOfEssentialDependency(sk);\n\n\n")





# ----------------- Plotting -----------------
import numpy as np
import matplotlib.pyplot as plt

def plot_evolution(all_data, timestamp, fitness_name):
    generations = len(all_data[0]['max'])
    avg_max = np.mean([run['max'] for run in all_data], axis=0)
    std_max = np.std([run['max'] for run in all_data], axis=0)
    avg_reach = np.mean([run['reachable'] for run in all_data], axis=0)
    std_reach = np.std([run['reachable'] for run in all_data], axis=0)

    # Find the best fitness trajectory
    best_fitness_overall = -np.inf
    best_run_idx = 0
    for i, run in enumerate(all_data):
        if max(run['max']) > best_fitness_overall:
            best_fitness_overall = max(run['max'])
            best_run_idx = i
    best_run = all_data[best_run_idx]

    plt.figure()
    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()

    # Plot all runs (light background)
    for i, run_data in enumerate(all_data):
        ax1.plot(run_data['max'], color='lightgray', linewidth=0.8)
        ax2.plot(run_data['reachable'], color='mistyrose', linewidth=0.8)

    # Plot average + std shading
    ax1.plot(avg_max, label='Average Max Fitness', color='blue', linewidth=2)
    ax1.fill_between(range(generations), avg_max - std_max, avg_max + std_max, color='blue', alpha=0.2)
    ax2.plot(avg_reach, label='Average Reachable States', color='red', linewidth=2)
    ax2.fill_between(range(generations), avg_reach - std_reach, avg_reach + std_reach, color='red', alpha=0.2)

    # Highlight best run
    ax1.plot(best_run['max'], label='Best Run Fitness', color='navy', linewidth=2.5)
    ax2.plot(best_run['reachable'], label='Best Run Reachable States', color='darkred', linewidth=2.5)

    # Labels and title
    ax1.set_xlabel('Generation')
    ax1.set_ylabel('Fitness', color='blue')
    ax2.set_ylabel('Reachable States', color='red')
    fig.suptitle(f'Evolution Metrics Over Time ({fitness_name})')

    # Legends, positioned below plot to avoid overlap
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    fig.legend(handles1 + handles2, labels1 + labels2, loc='lower center', ncol=2, bbox_to_anchor=(0.5, -0.10))

    plt.tight_layout()
    plt.savefig(f'evolution_metrics_{timestamp}.pdf', bbox_inches='tight')
    plt.close()

    print(f"Evolution metrics plot saved as evolution_metrics_{timestamp}.pdf")



#Part 4:  LaTeX Report and  Main
# ----------------- LaTeX Report -----------------
def create_prelim_report(fitness_name, env_variant, timestamp, best_per_run, params):
    with open(f"evolution_prelim_report_{timestamp}.tex", "w") as f:
        f.write("\\documentclass{article}\n")
        f.write("\\usepackage{xcolor}\n")
        f.write("\\usepackage{graphicx}\n")
        f.write("\\usepackage{placeins}\n")
        f.write("\\usepackage{geometry}\n")
        f.write("\\usepackage{listings}\n")
        f.write("\\geometry{margin=1in}\n\\begin{document}\n")
        f.write(f"\\title{{Evolution Strategy for Mealy Automata -- Fitness {fitness_name}")
        if fitness_name in ["Traversal", "MultiTraversal"]:
            f.write(f" (Environment DFA: {env_variant})")
        f.write("}\n\\maketitle\n")
        f.write("\\section*{Evolution Metrics and Parameters}\n")
        f.write(f"Population Size:{params['population_size']}  ")
        f.write(f"Offspring:{params['offspring_size']} ")
        f.write(f"Number of States:{params['num_states']} ")
        f.write(f"Runs:{params['runs']}  ")
        f.write(f"Generations:{params['generations']} \n")

        # Evolution metrics figure + caption
        f.write("\\begin{figure}[ht!]\n\\centering\n")
        f.write(f"\\includegraphics[width=\\linewidth]{{evolution_metrics_{timestamp}.pdf}}\n")
        f.write("\\FloatBarrier\n")
        
        # Get best automaton across runs
        best_auto, best_fitness, _, _ = max(best_per_run, key=lambda x: x[1])
        best_reachable = len(best_auto.get_reachable_states())
        f.write("\\caption{Evolutionary run summary for fitness function: "
                f"{fitness_name}. Parameters: population size = {params['population_size']}, "
                f"offspring size = {params['offspring_size']}, num states = {params['num_states']}, "
                f"runs = {params['runs']}, generations = {params['generations']}. "
                f"Best automaton fitness = {best_fitness}, "
                f"reachable states = {best_reachable}.  The average and standard deviation bands for fitness (blue) and number of reachable states (red) across all runs.  The trajectory of the best fitness run is highlighted as a darker blue line, and its corresponding reachable states are shown as a darker red line.")

        f.write(" }\n")
        f.write("\\end{figure}\n ")

        f.write("\\newpage\n")

        # Print Results of Each Run:
        for i, (automaton, fitness, pairs, _) in enumerate(best_per_run):
            run_id = i + 1
            run_dot_pdf = f"best_automaton_run_{run_id}_{timestamp}.pdf"
            run_dot_reach_pdf = f"best_automaton_run_{run_id}_{timestamp}_reachable.pdf"
            run_g_file = f"best_automaton_run_{run_id}_{timestamp}.g"
            run_g_reach_file = f"best_automaton_run_{run_id}_{timestamp}_reachable.g"

            reachable_states = len(automaton.get_reachable_states())

            f.write("\\newpage\n\\footnotesize\n")
            f.write(f"\\section*{{Run {run_id}}} \n")
            f.write(f"Fitness: {fitness_name} ")
            if fitness_name in ["Traversal", "MultiTraversal"]:
                f.write(f" (Environment DFA: {env_variant})\\\\ \n")
            if fitness_name == "Traversal": 
                f.write(f"Raw Fitness: {fitness+.1*reachable_states}, Fitness: {fitness},\\ Reachable States: {reachable_states}, \n")
            elif fitness_name == "MultiTraversal":
                total_fitness = pairs["total_fitness"]
                f.write(f"Total Fitness: {total_fitness}, Fitness: {fitness},\\ Reachable States: {reachable_states}, \n")
            else: 
                f.write(f"Raw Fitness: {fitness+reachable_states}, Fitness: {fitness},\\ Reachable States: {reachable_states}, \n")

            if fitness_name == "MultiTraversal":
                for result in pairs["per_start"]:
                    f.write(f"\\newline\\noindent{{\\bf Start at Environment State {result['start_state']+1}}} ")
                    f.write(f"\\newline Run Fitness: {result['run_fitness']} ")
                    traj_str = ""
                    for (inp, out), first_time in result['pairs']:
                        pair_str = f"({inp}, {out})"
                        if first_time:
                            pair_str = f"\\underline{{\\textcolor{{red}}{{{pair_str}}}}}"
                        traj_str += pair_str + " "
                    f.write("\\newline Trajectory: " + traj_str + "\n")
                    out_str = ""
                    for (inp, out), first_time in result['pairs']:
                        out_str += str(out)
                    f.write("\\newline Output: " + out_str + "\n")
            else:
                f.write("\n\\noindent{\\bf Trajectory (Input, Output) Pairs}\n")
                traj_str = ""
                seen_pairs = set()
                for (inp, out), first_time in pairs:
                    pair_str = f"({inp}, {out})"
                    if first_time:
                        pair_str = f"\\underline{{\\textcolor{{red}}{{{pair_str}}}}}"
                    traj_str += pair_str + " "
                f.write(traj_str + "\n")
                out_str = ""
                for (inp, out), first_time in pairs:
                    out_str += str(out)
                f.write("\n\\noindent Output: " + out_str + "\n")

            f.write("\\begin{figure}[h!]\n\\centering\n")
            f.write(f"\\includegraphics[width=0.45\\linewidth]{{{run_dot_pdf}}}\n")
            f.write(f"\\includegraphics[width=0.45\\linewidth]{{{run_dot_reach_pdf}}}\n")
            f.write("\\end{figure}\n")
            f.write("\\FloatBarrier\n")

            # Suppress Printing Code for Full Automaton with Unreachable States
            f.write("\n{\\bf GAP Transformations (Reachable States)}\n")
            f.write(f"\\lstinputlisting{{{run_g_reach_file}}}\n")

        f.write("\\end{document}\n")



def create_report(fitness_name, env_variant, timestamp, best_per_run, parsed_results, params):
    with open(f"evolution_report_{timestamp}.tex", "w") as f:
        f.write("\\documentclass{article}\n")
        f.write("\\usepackage{xcolor}\n")
        f.write("\\usepackage{graphicx}\n")
        f.write("\\usepackage{placeins}\n")
        f.write("\\usepackage{geometry}\n")
        f.write("\\usepackage{listings}\n")
        f.write("\\geometry{margin=1in}\n\\begin{document}\n")
        f.write(f"\\title{{Evolution Strategy for Mealy Automata -- Fitness {fitness_name}")
        if fitness_name in ["Traversal", "MultiTraversal"]:
            f.write(f" (Environment DFA: {env_variant})")
        f.write("}\n\\maketitle\n")
        f.write("\\section*{Evolution Metrics and Parameters}\n")
        f.write(f"Population Size:{params['population_size']}  ")
        f.write(f"Offspring:{params['offspring_size']} ")
        f.write(f"Number of States:{params['num_states']} ")
        f.write(f"Runs:{params['runs']}  ")
        f.write(f"Generations:{params['generations']} \n")

        # Evolution metrics figure + caption
        f.write("\\begin{figure}[ht!]\n\\centering\n")
        f.write(f"\\includegraphics[width=\\linewidth]{{evolution_metrics_{timestamp}.pdf}}\n")
        f.write("\\FloatBarrier\n")
        
        # Get best automaton across runs
        best_auto, best_fitness, _, _ = max(best_per_run, key=lambda x: x[1])
        best_reachable = len(best_auto.get_reachable_states())
        f.write("\\caption{Evolutionary run summary for fitness function: "
                f"{fitness_name}. Parameters: population size = {params['population_size']}, "
                f"offspring size = {params['offspring_size']}, num states = {params['num_states']}, "
                f"runs = {params['runs']}, generations = {params['generations']}. "
                f"Best automaton fitness = {best_fitness}, "
                f"reachable states = {best_reachable}.  The average and standard deviation bands for fitness (blue) and number of reachable states (red) across all runs.  The trajectory of the best fitness run is highlighted as a darker blue line, and its corresponding reachable states are shown as a darker red line.")

        f.write(" }\n")
        f.write("\\end{figure}\n ")


        f.write("\\newpage\n")


        # Per-Run plot
        f.write("\\section*{Per Run Complexity Bounds Plots}\n")
        f.write("\\begin{figure}[h!]\n\\centering\n")
        f.write(f"\\includegraphics[width=0.8\\linewidth]{{gap_per_run_summary_{timestamp}.pdf}}\n")
        
        # Prepare caption info
        caption_fitness = f"Fitness function:{fitness_name}"
        if fitness_name == "Traversal":
            caption_fitness += f" (Environment DFA:{env_variant})"
        if params.get('init_automaton_file'):
            init_method = f"Initialized from automaton file: {params['init_automaton_file']}"
        elif params.get('init_population_file'):
            init_method = f"Initialized from population file: {params['init_population_file']}"
        elif params.get('checkpoint_file'):
            init_method = f"Resumed from checkpoint: {params['checkpoint_file']}"
        else:
            init_method = f"Initialized with self_loop_init = {params.get('self_loop_init', 'False')}"
        init_method = init_method.replace('_', '\\_')
        caption_text = (
            f"Per-run summary: number of reachable states (blue), complexity upper bound (green), and max chain length (red), and maximum possible complexity (purple dashed, equals reachable states minus 1) plotted against run number."
            f" {caption_fitness}. "
            f"{init_method}. "
            f"Parameters: population size = {params['population_size']}, "
            f"offspring size = {params['offspring_size']}, "
            f"num states = {params['num_states']}, runs = {params['runs']}, "
            f"generations = {params['generations']}. "
        )
        f.write(f"\\caption{{{caption_text}}}\n")
        f.write("\\end{figure}\n")
        f.write("\\FloatBarrier\n")

        f.write("\\newpage\n")

        # Print Results of Each Run:
        for i, (automaton, fitness, pairs, _) in enumerate(best_per_run):
            run_id = i + 1
            run_dot_pdf = f"best_automaton_run_{run_id}_{timestamp}.pdf"
            run_dot_reach_pdf = f"best_automaton_run_{run_id}_{timestamp}_reachable.pdf"
            run_g_file = f"best_automaton_run_{run_id}_{timestamp}.g"
            run_g_reach_file = f"best_automaton_run_{run_id}_{timestamp}_reachable.g"

            reachable_states = len(automaton.get_reachable_states())

            f.write("\\newpage\n\\footnotesize\n")
            f.write(f"\\section*{{Run {run_id}}} \n")
            f.write(f"Fitness: {fitness_name} ")
            if fitness_name in ["Traversal", "MultiTraversal"]:
                f.write(f" (Environment DFA: {env_variant})\\\\ \n")
            if fitness_name == "Traversal": 
                f.write(f"Raw Fitness: {fitness+.1*reachable_states}, Fitness: {fitness},\\ Reachable States: {reachable_states}, \n")
            elif fitness_name == "MultiTraversal":
                total_fitness = pairs["total_fitness"]
                f.write(f"Total Fitness: {total_fitness}, Fitness: {fitness},\\ Reachable States: {reachable_states}, \n")
            else: 
                f.write(f"Raw Fitness: {fitness+reachable_states}, Fitness: {fitness},\\ Reachable States: {reachable_states}, \n")

            if fitness_name == "MultiTraversal":
                for result in pairs["per_start"]:
                    f.write(f"\\newline\\noindent{{\\bf Start at Environment State {result['start_state']+1}}} ")
                    f.write(f"\\newline Run Fitness: {result['run_fitness']} ")
                    traj_str = ""
                    for (inp, out), first_time in result['pairs']:
                        pair_str = f"({inp}, {out})"
                        if first_time:
                            pair_str = f"\\underline{{\\textcolor{{red}}{{{pair_str}}}}}"
                        traj_str += pair_str + " "
                    f.write("\\newline Trajectory: " + traj_str + "\n")
                    out_str = ""
                    for (inp, out), first_time in result['pairs']:
                        out_str += str(out)
                    f.write("\\newline Output: " + out_str + "\n")
            else:
                f.write("\n\\noindent{\\bf Trajectory (Input, Output) Pairs}\n")
                traj_str = ""
                seen_pairs = set()
                for (inp, out), first_time in pairs:
                    pair_str = f"({inp}, {out})"
                    if first_time:
                        pair_str = f"\\underline{{\\textcolor{{red}}{{{pair_str}}}}}"
                    traj_str += pair_str + " "
                f.write(traj_str + "\n")
                out_str = ""
                for (inp, out), first_time in pairs:
                    out_str += str(out)
                f.write("\n\\noindent Output: " + out_str + "\n")

            f.write("\\begin{figure}[h!]\n\\centering\n")
            f.write(f"\\includegraphics[width=0.45\\linewidth]{{{run_dot_pdf}}}\n")
            f.write(f"\\includegraphics[width=0.45\\linewidth]{{{run_dot_reach_pdf}}}\n")
            f.write("\\end{figure}\n")
            f.write("\\FloatBarrier\n")

            # Suppress Printing Code for Full Automaton with Unreachable States
            f.write("\n{\\bf GAP Transformations (Reachable States)}\n")
            f.write(f"\\lstinputlisting{{{run_g_reach_file}}}\n")

        f.write("\\end{document}\n")



# GAP REPORT -----------

def generate_gap_runner(best_per_run, timestamp):
    gap_script = f"gap_runner_{timestamp}.g"
    with open(gap_script, "w") as f:
        f.write('LoadPackage("SgpDec");\n')

        for i in range(len(best_per_run)):
            run_id = i + 1
            g_file = f"best_automaton_run_{run_id}_{timestamp}_reachable.g"
            f.write(f'Read("{g_file}");\n')
    print(f"GAP runner script written to {gap_script}")
    return gap_script

def run_gap_and_collect(gap_script, timestamp):
    gap_output_file = f"gap_output_{timestamp}.txt"
    with open(gap_output_file, "w") as outfile:
#         subprocess.run(f"../gap-4.13.1/gap -o 50g -b  < {gap_script}", stdout=outfile, shell=True)
        subprocess.run(f"gap -o 50g  < {gap_script}", stdout=outfile, shell=True)
    print(f"GAP output collected in {gap_output_file}")
    return gap_output_file

def clean_gap_output(gap_output_file):
    cleaned_file = gap_output_file.replace('.txt', '_cleaned.txt')
    if args.execution == "Sequential":
        sed_command = f"sed -r 's/\\x1b\\[[0-9;]*[mK]//g' {gap_output_file} > {cleaned_file}"
        subprocess.run(sed_command, shell=True)
    else:
        with open(gap_output_file, 'r') as infile:
            content = infile.read()

        # Remove lines that are just '>' or a series of '>' (possibly separated by spaces)
        content = re.sub(r'^([ >]+)$', '', content, flags=re.MULTILINE)
        # Remove any inline "> > > ..." fragments (e.g., at the start of a line)
        content = re.sub(r'(^|\n)[ >]+', '\n', content)
        # Remove multiple blank lines
        content = re.sub(r'\n\s*\n+', '\n', content)
        # Strip leading/trailing whitespace
        content = content.strip()

        with open(cleaned_file, 'w') as outfile:
            outfile.write(content)
    print(f"Cleaned GAP output saved to {cleaned_file}")
    return cleaned_file

def run_single_gap(gap_script, timestamp, run_id):
    output_file = f"gap_output_run_{run_id}_{timestamp}.txt"
    with open(output_file, "w") as outfile:
        result = subprocess.run(
            f"gap -o 50g < {gap_script}",
            stdout=outfile,
            stderr=subprocess.PIPE,
            shell=True
        )

    return output_file

#def clean_gap_output(gap_output_file):
#    cleaned_file = gap_output_file.replace('.txt', '_cleaned.txt')
#    # Use -E for macOS sed, -r for GNU sed; here I write it portable
#    sed_command = f"sed -E 's/\\x1b\\[[0-9;]*[mK]//g' {gap_output_file} > {cleaned_file}"
##    subprocess.run(sed_command, shell=True)
#    print(f"Cleaned GAP output saved to {cleaned_file}")
#    return cleaned_file


def parse_gap_output(cleaned_gap_file):
    results = []
    with open(cleaned_gap_file, 'r') as f:
        content = f.read()

    # Split the output into blocks per automaton (based on "gap>" / "<skeleton"  prompt)
    if args.execution == 'Sequential':
        blocks = content.strip().split("gap>")[1:]  # skip first preamble
    else:
        blocks = content.strip().split("<skeleton")[1:]  # skip first preamble


    for block in blocks:
        # Clean block (handle GAP \ continuations)
        block_cleaned = re.sub(r'\\\s*\n', '', block)

        if args.execution == "Parallel":
            block_cleaned = re.sub(r'\s*gap>\s*', '\n', block_cleaned)

        # Look for the key markers
        reachable_match = re.search(r'number of reachable states:\s*(\d+)', block_cleaned)
    
        if reachable_match:
            reachable = int(reachable_match.group(1))
    
            complexity_match = re.search(r'complexity upper bound:(\d+)', block_cleaned)
            complexity = int(complexity_match.group(1)) if complexity_match else None
    
            aperiodic_match = re.search(r'non-aperiodic:(\d+)', block_cleaned)
            is_aperiodic = (aperiodic_match.group(1) == '0') if aperiodic_match else None

            # find where holonomy data starts (right after non-aperiodic)
            holonomy_match = re.search(
                r'non-aperiodic:\d+\s*\n(.*?)(?=Max Chain|$)',
                block_cleaned,
                re.DOTALL
            )

            if holonomy_match:
                holonomy_text = holonomy_match.group(1).strip()
                #  Flatten: replace newlines with ', '
                holonomy_text = re.sub(r'\s*\n\s*', '; ', holonomy_text)
            else:
                holonomy_text = ''


            #  Only parse chain text if it's inside a valid block

            if args.execution == "Parallel":
                chain_match = re.search(
                    r'Maximum Chain Found:(.*?)(?:\n\n|\Z)',
                    block_cleaned,
                    re.DOTALL
                )
            else:
                chain_match = re.search(
                    r'Max Chain of Essential Dependencies: Maximum Chain Found:(.*?)(?:\n\n|\Z)',
                    block_cleaned,
                    re.DOTALL
                )

            if chain_match:
                chain_text = chain_match.group(1).replace('\n', ' ').strip()
                if is_aperiodic:
                    chain_length = 0
                else:
                    chain_length = chain_text.count('->') + 1 if chain_text else 0
       #         chain_length = chain_text.count('->') + 1
            else:
                chain_text = ''
                chain_length = 0

            results.append({
                'reachable_states': reachable,
                'complexity_upper': complexity,
                'is_aperiodic': is_aperiodic,
                'holonomy_text': holonomy_text,
                'chain_text': chain_text,
                'chain_length': chain_length
            })
        else:
            # Optionally skip if no reachable info
            continue


    print(f"Parsed {len(results)} automata from GAP output.")
    return results

def plot_complexity_vs_reachability(results, timestamp):
    reachables = [r['reachable_states'] for r in results]
    complexities = [r['complexity_upper'] for r in results]
    chains = [r['chain_length'] for r in results]

    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax2 = ax1.twinx()

    ax1.scatter(reachables, complexities, color='blue', label='Complexity Upper Bound')
# Commented Out two next line to prevent display of Max Chain
    ax2.set_ylabel('Max Chain Length', color='red')
    ax2.scatter(reachables, chains, color='red', label='Max Chain Length')

    ax1.set_xlabel('Number of Reachable States')
    ax1.set_ylabel('Complexity Upper Bound', color='blue')

#Comment out Chain Length from title (comment out one of the next two lines)
    fig.suptitle('Reachable States vs Complexity and Chain Length')
#    fig.suptitle('Reachable States vs Complexity')

    # Create a combined legend
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    fig.legend(handles1 + handles2, labels1 + labels2, loc='upper left', bbox_to_anchor=(0.1, 0.9))

    plt.tight_layout()
    plt.savefig(f'gap_complexity_plot_{timestamp}.pdf')
    plt.close()
    print(f"Complexity vs Reachability plot saved as gap_complexity_plot_{timestamp}.pdf")

def create_summary_excel(best_per_run, parsed_results, timestamp):
    rows = []
    for i, ((automaton, fitness, pairs, matches), gap_data) in enumerate(zip(best_per_run, parsed_results)):
        run_number = i + 1
        num_states = automaton.num_states
        num_reachable = gap_data['reachable_states']
        complexity_upper = gap_data['complexity_upper']
        chain_length = gap_data['chain_length']
        aperiodic = 'Yes' if gap_data['is_aperiodic'] else 'No'

        row = {
            'Run Number': run_number,
#            'Matches': matches,
            'Fitness': fitness,
            'Number of States': num_states,
            'Reachable States': num_reachable,
            'Complexity Upper Bound': complexity_upper,
            'Max Chain Length': chain_length,
            'Aperiodic': aperiodic
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    excel_file = f"automata_summary_{timestamp}.xlsx"
    df.to_excel(excel_file, index=False)
    print(f"Excel summary saved as {excel_file}")

def plot_per_run_summary(results, timestamp):
    run_numbers = list(range(1, len(results) + 1))
    reachables = [r['reachable_states'] for r in results]
    complexities = [r['complexity_upper'] for r in results]
    chains = [r['chain_length'] for r in results]
    max_possible_complexities = [max(r - 1, 0) for r in reachables]

    plt.figure(figsize=(10, 6))

    plt.plot(run_numbers, reachables, 'o-', color='blue', label='Reachable States')
    plt.plot(run_numbers, complexities, 's-', color='green', label='Complexity Upper Bound')
    plt.plot(run_numbers, chains, 'd-', color='red', label='Max Chain Length')
    plt.plot(run_numbers, max_possible_complexities, 'x--', color='purple', label='Max Possible Complexity (Reachable - 1)')

    plt.xlabel('Run Number')
    plt.ylabel('Value')
    plt.title('Per-Run Summary: Reachable States, Complexity Upper Bound and Lower Bound,  Max Possible Complexity')
#    plt.title('Per-Run Summary: Reachable States, Complexity Upper Bound,  Max Possible Complexity')

    plt.legend(loc='upper left')

    # Force Y-axis to start at 0
    max_y = max(reachables + complexities + chains )
    plt.ylim(0, max_y + 1)

    plt.tight_layout()
    plt.savefig(f'gap_per_run_summary_{timestamp}.pdf')
    plt.close()
    print(f"Per-run summary plot saved as gap_per_run_summary_{timestamp}.pdf")


def plot_per_run_summary_OLD(results, timestamp):
    run_numbers = list(range(1, len(results) + 1))
    reachables = [r['reachable_states'] for r in results]
    complexities = [r['complexity_upper'] for r in results]
    chains = [r['chain_length'] for r in results]

    plt.figure(figsize=(10, 6))

    plt.plot(run_numbers, reachables, 'o-', color='blue', label='Reachable States')
    plt.plot(run_numbers, complexities, 's-', color='green', label='Complexity Upper Bound')
    plt.plot(run_numbers, chains, 'd-', color='red', label='Max Chain Length')

    plt.xlabel('Run Number')
    plt.ylabel('Value')
    plt.title('Per-Run Summary: Reachable States, Complexity Upper and Lower Bounds')
    plt.legend(loc='upper left')

    plt.tight_layout()
    plt.savefig(f'gap_per_run_summary_{timestamp}.pdf')
    plt.close()
    print(f"Per-run summary plot saved as gap_per_run_summary_{timestamp}.pdf")


def create_gap_report(gap_output_file, timestamp, fitness_name, env_variant, params):
    # Clean the GAP output first
    cleaned_gap_file = clean_gap_output(gap_output_file)
    parsed_results = parse_gap_output(cleaned_gap_file)

    # Plot Complexity Bounds vs Reachable States
    plot_complexity_vs_reachability(parsed_results, args.stamp)

    # Plot Per-Run Reachable States and Complexity Bounds
    plot_per_run_summary(parsed_results, args.stamp)
    
# DONE BLEOW - not sure about escaped timestamp. Is that for dot output 
#    create_summary_excel(best_per_run, parsed_results, args.stamp)

    escaped_timestamp = timestamp.replace('_', '\\_')
    report_filename = f"gap_analysis_report_{timestamp}.tex"

    # Read cleaned GAP content
    with open(cleaned_gap_file, "r") as infile:
        gap_content = infile.read()

    # Create Summary Excel File
    create_summary_excel(best_per_run, parsed_results, timestamp)

    # Write LaTeX report
    with open(report_filename, "w") as f:
        f.write("\\documentclass{article}\n")
        f.write("\\usepackage{geometry}\n\\geometry{margin=1in}\n")
        f.write("\\usepackage{verbatim}\n")
        f.write("\\usepackage{graphicx}\n")
        f.write("\\usepackage{placeins}\n")
        f.write("\\begin{document}\n")
        f.write(f"\\title{{GAP Analysis Report {escaped_timestamp}}}\n\\maketitle\n")

        # Add experiment parameters
        f.write("\\section*{Experiment Parameters}\n")
        f.write(f"Fitness function: {fitness_name}")
        if fitness_name == "Traversal":
            f.write(f" (Environment DFA: {env_variant})")
        f.write(" \\\\\n")
        f.write(f"Population size: {params['population_size']} \\\\\n")
        f.write(f"Offspring size: {params['offspring_size']} \\\\\n")
        f.write(f"Number of states: {params['num_states']} \\\\\n")
        f.write(f"Runs: {params['runs']} \\\\\n")
        f.write(f"Generations: {params['generations']} \n")



        # Per-Run plot
        f.write("\\section*{Per Run Complexity Bounds Plots}\n")
        f.write("\\begin{figure}[h!]\n\\centering\n")
        f.write(f"\\includegraphics[width=0.8\\linewidth]{{gap_per_run_summary_{timestamp}.pdf}}\n")
            
        # Prepare caption info
        caption_fitness = f"Fitness function: {fitness_name}"
        if fitness_name == "Traversal":
            caption_fitness += f" (Environment DFA: {env_variant})"
    
        # Determine initialization method for clarity
        if params.get('init_automaton_file'):
            init_method = f"Initialized from automaton file: {params['init_automaton_file']}"
        elif params.get('init_population_file'):
            init_method = f"Initialized from population file: {params['init_population_file']}"
        elif params.get('checkpoint_file'):
            init_method = f"Resumed from checkpoint: {params['checkpoint_file']}"
        else:
            init_method = f"Initialized with self_loop_init = {params.get('self_loop_init', 'False')}"
        init_method = init_method.replace('_', '\\_')

        # Full caption
        caption_text = (
            f"Per-run summary: number of reachable states (blue), complexity upper bound (green), and max chain length (red), and maximum possible complexity (purple dashed, equals reachable states minus 1) plotted against run number."
            f" {caption_fitness}. "
            f"{init_method}. "
            f"Parameters: population size = {params['population_size']}, "
            f"offspring size = {params['offspring_size']}, "
            f"num states = {params['num_states']}, runs = {params['runs']}, "
            f"generations = {params['generations']}. "
            )

        f.write(f"\\caption{{{caption_text}}}\n")
        f.write("\\end{figure}\n")
        f.write("\\FloatBarrier\n")

        f.write("\\newpage\n")

#        # Complexity plot
#        f.write("{\\bf Complexity vs Reachability Plot}\n")
#        f.write("\\begin{figure}[h!]\n\\centering\n")
#        f.write(f"\\includegraphics[width=0.8\\linewidth]{{gap_complexity_plot_{timestamp}.pdf}}\n")
#        f.write("\\caption{Scatter plot showing each best-of-run automaton's number of reachable states (x-axis) vs its complexity upper bound (blue) and max chain length (red).}\n")
#        f.write("\\end{figure}\n")
#        f.write("\\FloatBarrier\n")


        # Add GAP output section
        f.write("\\section*{Collected GAP Output}\n")
        f.write("\\begin{verbatim}\n")
        f.write(gap_content)
        f.write("\n\\end{verbatim}\n")
        f.write("\\end{document}\n")

    print(f"GAP LaTeX report generated: {report_filename}")
#    parsed_results = parse_gap_output(cleaned_gap_file)
#    create_report(args.fitness, args.env_variant, args.stamp, best_per_run, parsed_results, params)
#    print(f"Report generated: evolution_report_{args.stamp}.tex")
       


# ----------------- Main -----------------
if __name__ == "__main__":
    # Timeline mode: generation snapshots, first perfect traversal, deferred GAP.
    # Keep MealyEvolutionTimeline.py beside this file.
    import sys
    if "--timeline" in sys.argv:
        sys.argv.remove("--timeline")
        from MealyEvolutionTimeline import main as timeline_main
        if "--source" not in sys.argv:
            sys.argv.extend(["--source", os.path.abspath(__file__)])
        try:
            sys.exit(timeline_main())
        except KeyboardInterrupt:
            print("Interrupted. Resume with --timeline --resume OUTPUT_DIRECTORY.", file=sys.stderr)
            sys.exit(130)


    # Helper function to parse booleans from string
    def str2bool(v):
        if isinstance(v, bool):
            return v
        return v.lower() in ('yes', 'true', 't', '1')

    import pickle  # make sure pickle is imported

    # Argparse setup 
    parser = argparse.ArgumentParser(description="Mealy Automaton Evolution Strategy")
    parser.add_argument('--population_size', type=int, default=50)
    parser.add_argument('--offspring_size', type=int, default=50)
    parser.add_argument('--num_states', type=int, default=10)
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--generations', type=int, default=100)
    parser.add_argument('--fitness', choices=["EightBall", "FogelPalindrome", "Traversal", "MultiTraversal"], default="EightBall",
                        help="Fitness function: EightBall, FogelPalindrome, Traversal, MultiTraversal")
    parser.add_argument("--env_variant", type=str, default="SimpleHardestEnvironment", help="Variant of EnvironmentDFA for Traversal/MultiTraversal fitness")
    parser.add_argument('--self_loop_init', type=str2bool, default=False, help="Initialize automata with self-looping transitions")
    parser.add_argument('--stamp', type=str, default=datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    parser.add_argument('--execution', type=str, choices=["Sequential", "Parallel"], default="Sequential")

    # New arguments for advanced initialization & checkpointing
    parser.add_argument('--init_automaton_file', type=str, default=None,
                        help='Path to a saved automaton file to initialize population.')
    parser.add_argument('--init_population_file', type=str, default=None,
                        help='Path to a saved population file (list of automata).')
    parser.add_argument('--checkpoint_file', type=str, default=None,
                        help='Path to a checkpoint pickle file to resume evolution.')
    parser.add_argument('--save_checkpoint', type=str2bool, default=True,
                        help='Whether to save a checkpoint at the end of the evolution.')

    args = parser.parse_args()



    # Prepare environment DFA if needed
    env_dfa = None
    if args.fitness == "Traversal":
        env_dfa = EnvironmentDFA(8, ['0', '1'], variant=args.env_variant)

    # Initialize input/output alphabets
    if args.fitness in ["Traversal", "MultiTraversal"]:
        input_alphabet = [str(i) for i in range(1, 9)]
    else:
        input_alphabet = DEFAULT_INPUT_ALPHABET

    output_alphabet = DEFAULT_OUTPUT_ALPHABET

    # ----------------- Initialization Logic -----------------
    if args.checkpoint_file:
        print(f"Loading checkpoint from {args.checkpoint_file}...")
        with open(args.checkpoint_file, 'rb') as f:
            checkpoint_data = pickle.load(f)
        population = checkpoint_data['population']
        best_overall = checkpoint_data['best_overall']
        best_per_run = checkpoint_data['best_per_run']
        print(f"Checkpoint loaded with population of size {len(population)}.")

    else:
        # Ensure mutually exclusive
        if args.init_automaton_file and args.init_population_file:
            raise ValueError("Specify only one of --init_automaton_file or --init_population_file.")

        if args.init_population_file:
            print(f"Loading initial population from {args.init_population_file}...")
            with open(args.init_population_file, 'rb') as f:
                population = pickle.load(f)
            if len(population) < args.population_size:
                print(f"Population too small ({len(population)}); cloning to fill up to {args.population_size}.")
                population += [
                    copy.deepcopy(random.choice(population))
                    for _ in range(args.population_size - len(population))
                ]
            population = population[:args.population_size]

        elif args.init_automaton_file:
            print(f"Loading initial automaton from {args.init_automaton_file}...")
            with open(args.init_automaton_file, 'rb') as f:
                loaded_automaton = pickle.load(f)
            population = [copy.deepcopy(loaded_automaton) for _ in range(args.population_size)]

        else:
            print(f"Initializing population with self_loop_init={args.self_loop_init}...")
            population = [
                MealyAutomaton(
                    args.num_states,
                    input_alphabet,
                    output_alphabet,
                    self_loop_init=args.self_loop_init
                )
                for _ in range(args.population_size)
            ]

    # ----------------- Run Evolution -----------------
    all_data, best_overall, best_per_run = evolution_strategy(
        population,
        args.runs,
        args.generations,
        args.offspring_size,
        args.fitness,
        args.env_variant,
        args.stamp
    )


    # ----------------- Checkpoint Save -----------------
    if args.save_checkpoint:
        checkpoint_data = {
            'population': population,
            'best_overall': best_overall,
            'best_per_run': best_per_run,
            'timestamp': args.stamp,
            'params': {
                'population_size': args.population_size,
                'offspring_size': args.offspring_size,
                'num_states': args.num_states,
                'runs': args.runs,
                'generations': args.generations,
                'fitness_name': args.fitness,
                'env_variant': args.env_variant,
                'execution-mode': args.execution,
            }
        }
        with open(f'checkpoint_{args.stamp}.pkl', 'wb') as f:
            pickle.dump(checkpoint_data, f)
        print(f"Checkpoint saved as checkpoint_{args.stamp}.pkl")

    # Save best automata as .pkl files
    with open(f'best_automaton_overall_{args.stamp}.pkl', 'wb') as f:
        pickle.dump(best_overall, f)
    with open(f'best_per_run_{args.stamp}.pkl', 'wb') as f:
        pickle.dump(best_per_run, f)
    print(f"Best automata saved as pickle files.")

    # ----------------- Post-processing -----------------
    params = {
        'runs': args.runs,
        'generations': args.generations,
        'population_size': args.population_size,
        'offspring_size': args.offspring_size,
        'num_states': args.num_states,
        'self_loop_init': args.self_loop_init
    }

    plot_evolution(all_data, args.stamp, args.fitness)

    # Preliminary report before GAP analysis
    create_prelim_report(args.fitness, args.env_variant, args.stamp, best_per_run, params) #WITHOUT PARSED RESULTS, WITHOUT COMPLEXITY BOUNDS PLOT
    print(f"Preliminary report created as evolution_prelim_report_{args.stamp}.pdf")

     # GAP integration
    if args.execution == 'Sequential':
        gap_script = generate_gap_runner(best_per_run, args.stamp)
        gap_output_file = run_gap_and_collect(gap_script, args.stamp)
    else:
        # --- Parallel GAP integration ---
        g_files = [f"best_automaton_run_{i+1}_{args.stamp}_reachable.g" for i in range(len(best_per_run))]
        run_ids = list(range(1, len(best_per_run) + 1))

        ncpus = int(os.environ.get('SLURM_CPUS_PER_TASK', default=mp.cpu_count()))
        pool = mp.Pool(processes=ncpus)
        output_files = pool.starmap(run_single_gap, [(g, args.stamp, rid) for g, rid in zip(g_files, run_ids)])

        gap_output_file = f"gap_output_{args.stamp}.txt"
        with open(gap_output_file, "w") as outfile:
            for fname in output_files:
                with open(fname) as infile:
                    outfile.write(infile.read())

    cleaned_gap_file = clean_gap_output(gap_output_file)
    create_gap_report(cleaned_gap_file, args.stamp, args.fitness, args.env_variant, params)

    # List: also create the excel file and evolution report
    create_summary_excel(best_per_run, parse_gap_output(cleaned_gap_file), args.stamp)
    parsed_results = parse_gap_output(cleaned_gap_file)
    create_report(args.fitness, args.env_variant, args.stamp, best_per_run, parsed_results, params)


