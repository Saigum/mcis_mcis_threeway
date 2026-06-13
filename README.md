## Maximum Common Induced Node Subgraph between multiple large connectomes

This is a class of problem in graph iterature commonly referred to as MCS. Formally speaking, you're given 2 graphs, and the goal is to find a bijection of subsets of nodes such that, the induced graphs formed by both nodesets, are isomorphic.
MCS typically acts on two graphs, MMCS is normally whats used to act on 3 graphs.

The issue with typically MMCS subroutines, is that theyre usually defined with smaller pattern graphs in mind, and are usually more broad(greater number of graphs coverage). Our problem is kind of the opposite, we have 3 large graphs, out of which we want to find the biggest mcs. 

So, I chose a heuristic approach to this, instead, I chose an algorithm , that continually solves for an MCS, returning best intermediate MCS for two chosen graphs as it continually  solved it, took the topk smaller MCS's of this graph, and ran MCS between k of these candidates, with each of them acting as  pattern graph, and a 3rd graph acting as a target graph. 

Additionally, I didnt run this on the entire graphs, rather, I tried a bunch of graph subsampling strategies, two of which worked the best.
1. Hub-Biased Subsampling:  Here I heuristically define a hub node, as one that has an outdegree much greater than its indegree, and the outdegree is of a sufficiently high value(threshold set). I then sample nodes like this as a seed, and I run bfs from these seed nodes, post this, I choose all nodes, and consider the induced subgraph of these nodes, as a pattern/target graph.
2. High-degree biased subsampling: A similar idea to above, however instead of sampling hub nodes, i simply have a weighted sampler choose nodes of high degree.

#### Main method
Now the MCS subroutine, 
For my purposes, I choose symsplit, from the 2026 paper(Accelerating Maximum Common Subgraph Computation by
Exploiting Symmetries), and modified it to work for directed graphs. Essentially what that means is, I changed the validity checker of the algorithm, to return true only if the graph was a valid induced node directed subgraph. 