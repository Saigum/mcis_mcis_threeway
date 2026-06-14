# Largest Component Average Outdegree By Cell Type

Outdegree here is the induced outdegree inside the 1,540-node largest weak-component triplet node set, computed separately from each dataset's raw edge list.

MCNS caveat: this workspace does not contain a local MCNS root-id to primary-type table, so the MCNS table is grouped by the paired FAFB `primary_type` from the triplet mapping.

Full CSVs: `/home/saigum/Desktop/mcis_mcis_threeway/outputs/high_degree_bfs_20K/avg_outdegree_by_cell_type_banc.csv`, `/home/saigum/Desktop/mcis_mcis_threeway/outputs/high_degree_bfs_20K/avg_outdegree_by_cell_type_fafb.csv`, `/home/saigum/Desktop/mcis_mcis_threeway/outputs/high_degree_bfs_20K/avg_outdegree_by_cell_type_mcns_by_mapped_fafb_type.csv`.

## BANC

| cell_type | cells | avg_outdegree | median_outdegree | max_outdegree | total_outdegree |
| --- | ---: | ---: | ---: | ---: | ---: |
| APL | 1 | 1141.0000 | 1141.0000 | 1141 | 1141 |
| V_ilPN | 1 | 70.0000 | 70.0000 | 70 | 70 |
| lLN2P_c | 2 | 6.0000 | 6.0000 | 10 | 12 |
| PS157 | 1 | 5.0000 | 5.0000 | 5 | 5 |
| AN05B050 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| ATL014 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| DM5_lPN | 1 | 4.0000 | 4.0000 | 4 | 4 |
| M_ilPNm90 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| PLP143 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| AN05B101 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| AVLP316 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| CB1611 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| CL261b | 1 | 3.0000 | 3.0000 | 3 | 3 |
| CRE106 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| LHAV2o1 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| LHCENT2 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| M_vPNml67 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| SLP437 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| SLP465b | 1 | 3.0000 | 3.0000 | 3 | 3 |
| SMP075b | 1 | 3.0000 | 3.0000 | 3 | 3 |

### BANC Types With At Least 5 Cells

| cell_type | cells | avg_outdegree | median_outdegree | max_outdegree | total_outdegree |
| --- | ---: | ---: | ---: | ---: | ---: |
| ORN_V | 22 | 1.0000 | 1.0000 | 1 | 22 |
| KCab-s | 5 | 1.0000 | 1.0000 | 1 | 5 |
| KCab-p | 21 | 0.9524 | 1.0000 | 2 | 20 |
| KCab | 376 | 0.8883 | 1.0000 | 3 | 334 |
| KCg-d | 50 | 0.8400 | 1.0000 | 2 | 42 |
| KCapbp-ap2 | 38 | 0.7632 | 1.0000 | 2 | 29 |
| KCg-m | 546 | 0.7344 | 1.0000 | 3 | 401 |
| KCapbp-ap1 | 58 | 0.7069 | 1.0000 | 2 | 41 |
| KCab-m | 36 | 0.6667 | 1.0000 | 2 | 24 |
| untyped | 79 | 0.6582 | 1.0000 | 2 | 52 |
| KCab-c | 9 | 0.5556 | 1.0000 | 1 | 5 |
| KCapbp-m | 34 | 0.5294 | 1.0000 | 1 | 18 |

## FAFB

| cell_type | cells | avg_outdegree | median_outdegree | max_outdegree | total_outdegree |
| --- | ---: | ---: | ---: | ---: | ---: |
| CT1 | 1 | 1141.0000 | 1141.0000 | 1141 | 1141 |
| cL21 | 1 | 70.0000 | 70.0000 | 70 | 70 |
| LC11 | 1 | 10.0000 | 10.0000 | 10 | 10 |
| Li22 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| Li27 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| AN_multi_4 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| HSS | 1 | 3.0000 | 3.0000 | 3 | 3 |
| MeMe_e07 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| Tlp1 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| Li14 | 3 | 2.6667 | 2.0000 | 4 | 8 |
| LPT50 | 2 | 2.5000 | 2.5000 | 3 | 5 |
| Li16 | 3 | 2.0000 | 1.0000 | 4 | 6 |
| Li17 | 3 | 2.0000 | 2.0000 | 3 | 6 |
| Lawf2 | 2 | 2.0000 | 2.0000 | 2 | 4 |
| AVLP077 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| AVLP537 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB0732 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB1906 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB3667 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB3693 | 1 | 2.0000 | 2.0000 | 2 | 2 |

### FAFB Types With At Least 5 Cells

| cell_type | cells | avg_outdegree | median_outdegree | max_outdegree | total_outdegree |
| --- | ---: | ---: | ---: | ---: | ---: |
| LMa2 | 6 | 1.8333 | 1.0000 | 5 | 11 |
| LPi05 | 6 | 1.3333 | 1.0000 | 4 | 8 |
| Tm3 | 12 | 1.2500 | 1.0000 | 3 | 15 |
| LC9 | 6 | 1.1667 | 1.0000 | 3 | 7 |
| Tm9 | 83 | 1.0723 | 1.0000 | 3 | 89 |
| Mi1 | 73 | 1.0548 | 1.0000 | 3 | 77 |
| T4a | 27 | 1.0000 | 1.0000 | 1 | 27 |
| LMt2 | 7 | 1.0000 | 1.0000 | 2 | 7 |
| T2a | 7 | 1.0000 | 1.0000 | 3 | 7 |
| Tm1 | 7 | 1.0000 | 1.0000 | 1 | 7 |
| T4c | 76 | 0.9868 | 1.0000 | 1 | 75 |
| T4b | 208 | 0.9327 | 1.0000 | 2 | 194 |
| T4d | 125 | 0.9200 | 1.0000 | 1 | 115 |
| C3 | 8 | 0.8750 | 1.0000 | 3 | 7 |
| Y3 | 12 | 0.8333 | 1.0000 | 1 | 10 |

## MCNS (Grouped By Paired FAFB Type)

| cell_type | cells | avg_outdegree | median_outdegree | max_outdegree | total_outdegree |
| --- | ---: | ---: | ---: | ---: | ---: |
| CT1 | 1 | 1141.0000 | 1141.0000 | 1141 | 1141 |
| cL21 | 1 | 70.0000 | 70.0000 | 70 | 70 |
| LC11 | 1 | 10.0000 | 10.0000 | 10 | 10 |
| Li22 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| Li27 | 1 | 4.0000 | 4.0000 | 4 | 4 |
| AN_multi_4 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| HSS | 1 | 3.0000 | 3.0000 | 3 | 3 |
| MeMe_e07 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| Tlp1 | 1 | 3.0000 | 3.0000 | 3 | 3 |
| Li14 | 3 | 2.6667 | 2.0000 | 4 | 8 |
| LPT50 | 2 | 2.5000 | 2.5000 | 3 | 5 |
| Li16 | 3 | 2.0000 | 1.0000 | 4 | 6 |
| Li17 | 3 | 2.0000 | 2.0000 | 3 | 6 |
| Lawf2 | 2 | 2.0000 | 2.0000 | 2 | 4 |
| AVLP077 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| AVLP537 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB0732 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB1906 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB3667 | 1 | 2.0000 | 2.0000 | 2 | 2 |
| CB3693 | 1 | 2.0000 | 2.0000 | 2 | 2 |

### MCNS Proxy Types With At Least 5 Cells

| cell_type | cells | avg_outdegree | median_outdegree | max_outdegree | total_outdegree |
| --- | ---: | ---: | ---: | ---: | ---: |
| LMa2 | 6 | 1.8333 | 1.0000 | 5 | 11 |
| LPi05 | 6 | 1.3333 | 1.0000 | 4 | 8 |
| Tm3 | 12 | 1.2500 | 1.0000 | 3 | 15 |
| LC9 | 6 | 1.1667 | 1.0000 | 3 | 7 |
| Tm9 | 83 | 1.0723 | 1.0000 | 3 | 89 |
| Mi1 | 73 | 1.0548 | 1.0000 | 3 | 77 |
| T4a | 27 | 1.0000 | 1.0000 | 1 | 27 |
| LMt2 | 7 | 1.0000 | 1.0000 | 2 | 7 |
| T2a | 7 | 1.0000 | 1.0000 | 3 | 7 |
| Tm1 | 7 | 1.0000 | 1.0000 | 1 | 7 |
| T4c | 76 | 0.9868 | 1.0000 | 1 | 75 |
| T4b | 208 | 0.9327 | 1.0000 | 2 | 194 |
| T4d | 125 | 0.9200 | 1.0000 | 1 | 115 |
| C3 | 8 | 0.8750 | 1.0000 | 3 | 7 |
| Y3 | 12 | 0.8333 | 1.0000 | 1 | 10 |
