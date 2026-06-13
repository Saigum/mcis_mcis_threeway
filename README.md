## Maximum Common Induced Node Subgraph between multiple large connectomes

This is a class of problem in graph iterature commonly referred to as MCS. Formally speaking, you're given 2 graphs, and the goal is to find a bijection of subsets of nodes such that, the induced graphs formed by both nodesets, are isomorphic.
MCS typically acts on two graphs, MMCS is normally whats used to act on 3 graphs.

The issue with typically MMCS subroutines, is that theyre usually defined with smaller pattern graphs in mind, and are usually more broad(greater number of graphs coverage). Our problem is kind of the opposite, we have 3 large graphs, out of which we want to find the biggest mcs. 

So, I chose a heuristic approach to this, instead, I chose an algorithm , that continually solves for an MCS, returning best intermediate MCS for two chosen graphs as it continually  solved it, took the topk smaller MCS's of this graph, and ran MCS between k of these candidates, with each of them acting as  pattern graph, and a 3rd graph acting as a target graph. 

Additionally, I didnt run this on the entire graphs, rather, I tried a bunch of graph subsampling strategies, two of which worked the best.
1. Hub-Biased Subsampling:  Here I heuristically define a hub node, as one that has an outdegree much greater than its indegree, and the outdegree is of a sufficiently high value(threshold set). I then sample nodes like this as a seed, and I run bfs from these seed nodes, post this, I choose all nodes, and consider the induced subgraph of these nodes, as a pattern/target graph.
2. High-degree biased subsampling: A similar idea to above, however instead of sampling hub nodes, i simply have a weighted sampler choose nodes of high degree.

#### Main method
Now the MCS subroutine.
For this project, I use a staged heuristic around an exact pairwise solver rather than trying to solve the full multi-graph problem in one shot. This choice is motivated by the fact that maximum common subgraph is already NP-hard for two graphs, and the multi-graph extension becomes even harder in practice. Cardone and Quer's *The Multi-Maximum and Quasi-Maximum Common Subgraph Problem* (2023) is especially relevant here: it argues that exact multi-graph MCS procedures quickly become too expensive, and that heuristic decompositions are often the only practical way to scale to larger instances. That is the methodological reason I do not directly run a monolithic MMCS solver on the full connectomes.

So, the pipeline is:
1. choose a biologically motivated subsample of each graph
2. solve an exact or near-exact pairwise MCS on two graphs
3. keep strong intermediate pairwise candidates
4. reuse those candidates as pattern graphs against the third graph
5. retain only those correspondences whose row-wise induced directed subgraphs remain isomorphic across all three graphs

For the exact pairwise kernel, I chose SymSplit/ARCIS-style symmetry-aware branch-and-bound from Kothalawala, Koehler, and Farhan's *Accelerating Maximum Common Subgraph Computation by Exploiting Symmetries* (2026), because the whole point of that line of work is to reduce redundant exploration of isomorphic search branches. That is a good fit for connectome subgraph search, where repeated local wiring motifs and automorphisms can otherwise waste a large amount of search. I modified the solver-side validity logic to enforce a directed induced-node interpretation: a candidate mapping is accepted only if adjacency and non-adjacency are both preserved under direction, ignoring self-loops in the downstream validation pass.

This solver choice is also consistent with the broader modern MCS literature. Zhou et al.'s *A Strengthened Branch and Bound Algorithm for the Maximum Common (Connected) Subgraph Problem* (2022) shows that careful branching and pruning design still matters a great deal for exact MCS. Yu et al.'s *Fast Maximum Common Subgraph Search: A Redundancy-Reduced Backtracking Approach* (2025) pushes the same idea further with redundancy-reduced backtracking in RRSplit. ARCIS then adds stronger symmetry handling on top of that style of exact search. In other words, the exact subroutine used here is not ad hoc; it follows the current branch-and-bound/backtracking tradition for high-performance MCS.

I did not use a learning-based solver, even though Bai et al.'s *GLSearch: Maximum Common Subgraph Detection via Learning to Search* (2021) is a relevant alternative. The reason is methodological rather than philosophical: for this project I wanted a deterministic search core whose failures and intermediate incumbents were easy to inspect, revalidate, and recycle into the third-graph stage. That made a symmetry-aware exact solver a better fit than a learned search policy.

In summary, the method is a heuristic three-graph reduction built around a strong exact two-graph MCS engine. The heuristics enter at the sampling stage and at the "pairwise first, third-graph later" decomposition; the exactness enters when validating candidate node correspondences as directed induced subgraphs under the chosen row-wise mapping.

#### How to use this repository
At a high level, the repository has three parts:
1. `raw_graphs/` contains the directed edge lists used for validation and downstream induced-subgraph analysis.
2. `outputs/` contains the sampled runs, pairwise/triple candidate correspondences, and the follow-up analyses on the best matched triplets.
3. `flywire_wrappers/` contains the scripts used to validate matches, compute component structure, and add biological interpretation.

The most useful entry files for the current `high_degree_bfs_20K` result are:
1. `network.csv`: the current matched triplet node list for the largest weak component only.
2. `outputs/high_degree_bfs_20K/largest_weak_component_triplet/banc_626__fafb_783__mcns_0.9/`: the saved largest-component triplet analysis folder.
3. `outputs/high_degree_bfs_20K/largest_component_source_hub_analysis/`: SCC condensation and source/core/sink structure on that component.
4. `outputs/high_degree_bfs_20K/fafb_recurrent_mesoscale_report/`: FAFB-based biological interpretation and figures.

If the goal is to verify that a matched node list is a valid directed induced three-way match, the simplest workflow is:
1. prepare a CSV whose first three columns are the matched node IDs for the three graphs, one triplet per row
2. use the raw graph edge lists to build the induced edge set on those nodes for each graph
3. compare the three induced directed edge sets under row position, ignoring self-loops
4. only keep the node list if all three induced edge sets are identical

That is exactly the validation logic used in the repository's three-way isomorphism scripts.

If the goal is biological interpretation after a match has already been found, the workflow is:
1. restrict to the largest weak component of the matched triplet
2. collapse strongly connected components to a condensation DAG
3. identify recurrent core, source-like hubs, sinks, and intermediates
4. join available cell-type and class annotations
5. use enrichment and composition plots to turn graph structure into a biological narrative
