.. _pbc:

*******************************************
pbc --- Periodic boundary conditions
*******************************************
The :mod:`pbc` module provides electronic structure implementations with periodic boundary
conditions based on periodic Gaussian basis functions. The PBC implementation supports
both all-electron and pseudopotential descriptions.

In PySCF, the PBC implementation has a tight relation to the molecular implementation.
The module names, function names, and layouts of the PBC code are the same as (or as close
as possible to) those of the molecular code.  The PBC code supports the use (and mixing)
of basis sets, pseudopotentials, and effective core potentials developed accross the
materials science and quantum chemistry communites, offering great flexibility.  Moreover,
many post-mean-field methods defined in the molecular code can be seamlessly mixed with
PBC calculations performed at the gamma point.  For example, one can perform a gamma-point
Hartree-Fock calculation in a supercell, followed by a CCSD(T) calculation, which is
implemented in the molecular code.

In PBC calculations that sample the Brillouin zone beyond the gamma point (i.e. with
k-point sampling), we make small changes to the gamma-point data structures and export KHF
and KDFT methods.  On top of these KSCF methods, we have implemented k-point CCSD and
k-point EOM-CCSD methods.  Other post-mean-field methods can be analogously written to
explicitly enforce translational symmetry through k-point sampling.

The list of modules described in this chapter is:

.. toctree::

   pbc/gto.rst
   pbc/scf.rst
   pbc/dft.rst
   pbc/df.rst
   pbc/cc.rst
   pbc/tools.rst
   pbc/mix_mol.rst

