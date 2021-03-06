#!/usr/bin/env python

'''
IBO generation, cube generation, and population analysis of benzene
'''

import numpy
from pyscf import gto, scf, lo, tools

benzene = [[ 'C'  , ( 4.673795 ,   6.280948 , 0.00  ) ], 
           [ 'C'  , ( 5.901190 ,   5.572311 , 0.00  ) ],
           [ 'C'  , ( 5.901190 ,   4.155037 , 0.00  ) ],
           [ 'C'  , ( 4.673795 ,   3.446400 , 0.00  ) ],
           [ 'C'  , ( 3.446400 ,   4.155037 , 0.00  ) ],
           [ 'C'  , ( 3.446400 ,   5.572311 , 0.00  ) ],
           [ 'H'  , ( 4.673795 ,   7.376888 , 0.00  ) ],
           [ 'H'  , ( 6.850301 ,   6.120281 , 0.00  ) ],
           [ 'H'  , ( 6.850301 ,   3.607068 , 0.00  ) ],
           [ 'H'  , ( 4.673795 ,   2.350461 , 0.00  ) ],
           [ 'H'  , ( 2.497289 ,   3.607068 , 0.00  ) ],
           [ 'H'  , ( 2.497289 ,   6.120281 , 0.00  ) ]]

mol = gto.M(atom=benzene,
            basis='ccpvdz')
mf = scf.RHF(mol).run()

mo_occ = mf.mo_coeff[:,mf.mo_occ>0]
a = lo.iao.iao(mol, mo_occ)

# Orthogonalize IAO
a = lo.vec_lowdin(a, mf.get_ovlp())


'''
Generate IBOS from orthogonal IAOs
'''

ibo = lo.ibo.ibo(mol, mo_occ, a, mf)

'''
Print the IBOS into Gausian Cube files
'''

for i in range(ibo.shape[1]):
     tools.cubegen.density(mol, 'benzene_ibo_'+str(i+1)+'.cube', ibo ,moN=i+1)

'''
Population Analysis with IAOS 
'''
# transform mo_occ to IAO representation. Note the AO dimension is reduced
mo_occ = reduce(numpy.dot, (a.T, mf.get_ovlp(), mo_occ))

#constructs the density matrix in the new representation
dm = numpy.dot(mo_occ, mo_occ.T) * 2

#mullikan population analysis based on IAOs
pmol = mol.copy()
pmol.build(False, False, basis='minao')
mf.mulliken_pop(pmol, dm, s=numpy.eye(pmol.nao_nr()))
