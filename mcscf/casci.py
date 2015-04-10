#!/usr/bin/env python
#
# Author: Qiming Sun <osirpt.sun@gmail.com>
#

import tempfile
import time
from functools import reduce
import numpy
import scipy.linalg
import h5py
import pyscf.lib
from pyscf.lib import logger
import pyscf.scf
from pyscf import ao2mo
from pyscf import fci
from pyscf.tools.mo_mapping import mo_1to1map


def extract_orbs(mo_coeff, ncas, nelecas, ncore):
    nocc = ncore + ncas
    mo_core = mo_coeff[:,:ncore]
    mo_cas = mo_coeff[:,ncore:nocc]
    mo_vir = mo_coeff[:,nocc:]
    return mo_core, mo_cas, mo_vir

def h1e_for_cas(casci, mo_coeff=None, ncas=None, ncore=None):
    '''CAS sapce one-electron hamiltonian

    Args:
        casci : a CASSCF/CASCI object or RHF object

    Returns:
        A tuple, the first is the effective one-electron hamiltonian defined in CAS space,
        the second is the electronic energy from core.
    '''
    if mo_coeff is None: mo_coeff = casci.mo_coeff
    if ncas is None: ncas = casci.ncas
    if ncore is None: ncore = casci.ncore
    mo_core = mo_coeff[:,:ncore]
    mo_cas = mo_coeff[:,ncore:ncore+ncas]

    hcore = casci.get_hcore()
    if mo_core.size == 0:
        corevhf = 0
        energy_core = 0
    else:
        core_dm = numpy.dot(mo_core, mo_core.T) * 2
        corevhf = casci.get_veff(casci.mol, core_dm)
        energy_core = numpy.einsum('ij,ji', core_dm, hcore) \
                    + numpy.einsum('ij,ji', core_dm, corevhf) * .5
    h1eff = reduce(numpy.dot, (mo_cas.T, hcore+corevhf, mo_cas))
    return h1eff, energy_core

def analyze(casscf, mo_coeff=None, ci=None, verbose=logger.INFO):
    from pyscf.tools import dump_mat
    from pyscf.mcscf import mc_ao2mo
    from pyscf.mcscf import addons
    if mo_coeff is None: mo_coeff = casscf.mo_coeff
    if ci is None: ci = casscf.ci
    if isinstance(verbose, logger.Logger):
        log = verbose
    else:
        log = logger.Logger(casscf.stdout, verbose)
    nelecas = casscf.nelecas
    ncas = casscf.ncas
    ncore = casscf.ncore
    nocc = ncore + ncas
    nmo = mo_coeff.shape[1]

    casdm1a, casdm1b = casscf.fcisolver.make_rdm1s(ci, ncas, nelecas)
    dm1a = addons._make_rdm1_on_mo(casdm1a, ncore, ncas, nmo, False)
    dm1b = addons._make_rdm1_on_mo(casdm1b, ncore, ncas, nmo, False)
    dm1a = reduce(numpy.dot, (mo_coeff, dm1a, mo_coeff.T))
    dm1b = reduce(numpy.dot, (mo_coeff, dm1b, mo_coeff.T))

    if log.verbose >= logger.INFO:
        label = ['%d%3s %s%-4s' % x for x in casscf.mol.spheric_labels()]
        if log.verbose >= logger.DEBUG:
            log.info('alpha density matrix (on AO)')
            dump_mat.dump_tri(log.stdout, dm1a, label)
            log.info('beta density matrix (on AO)')
            dump_mat.dump_tri(log.stdout, dm1b, label)

        log.info('Natural orbital in CAS space')
        dump_mat.dump_rec(log.stdout, mo_coeff[:,ncore:nocc], label, start=1)

        s = reduce(numpy.dot, (casscf.mo_coeff.T, casscf._scf.get_ovlp(),
                               casscf._scf.mo_coeff))
        idx = numpy.argwhere(abs(s)>.4)
        for i,j in idx:
            log.info('<mo-mcscf|mo-hf> %d, %d, %12.8f' % (i+1,j+1,s[i,j]))

        log.info('** Largest CI components **')
        log.info(' string alpha, string beta, CI coefficients')
        for c,ia,ib in fci.addons.large_ci(ci, casscf.ncas, casscf.nelecas):
            log.info('  %9s    %9s    %.12f', ia, ib, c)

        dm1 = dm1a + dm1b
        s = casscf._scf.get_ovlp()
        casscf._scf.mulliken_pop(casscf.mol, dm1, s, verbose=log)
        casscf._scf.mulliken_pop_meta_lowdin_ao(casscf.mol, dm1, verbose=log)
    return dm1a, dm1b

def get_fock(mc, mo_coeff=None, ci=None, eris=None, verbose=None):
    '''Generalized Fock matrix
    '''
    from pyscf.mcscf import mc_ao2mo
    if ci is None: ci = mc.ci
    if mo_coeff is None: mo_coeff = mc.mo_coeff
    if eris is None:
        if hasattr(mc, 'update_ao2mo'):
            eris = mc.update_ao2mo(mo_coeff)
        else: # CASCI
            eris = mc_ao2mo._ERIS(mc, mo_coeff, approx=2)
    ncore = mc.ncore
    ncas = mc.ncas
    nelecas = mc.nelecas

    casdm1 = mc.fcisolver.make_rdm1(ci, ncas, nelecas)
    vj = numpy.einsum('ij,ijpq->pq', casdm1, eris.aapp)
    vk = numpy.einsum('ij,ipqj->pq', casdm1, eris.appa)
    h1 = reduce(numpy.dot, (mo_coeff.T, mc.get_hcore(), mo_coeff))
    fock = h1 + eris.vhf_c + vj - vk * .5
    return fock

def cas_natorb(mc, mo_coeff=None, ci=None, eris=None, verbose=None):
    '''Restore natrual orbitals
    '''
    if isinstance(verbose, logger.Logger):
        log = verbose
    else:
        log = logger.Logger(mc.stdout, mc.verbose)
    if mo_coeff is None: mo_coeff = mc.mo_coeff
    if ci is None: ci = mc.ci
    if eris is None:
        if hasattr(mc, 'update_ao2mo'):
            eris = mc.update_ao2mo(mo_coeff)
        else: # CASCI
            eris = mc_ao2mo._ERIS(mc, mo_coeff, approx=2)
    ncore = mc.ncore
    ncas = mc.ncas
    nocc = ncore + ncas
    nelecas = mc.nelecas
    casdm1 = mc.fcisolver.make_rdm1(ci, ncas, nelecas)
    occ, ucas = scipy.linalg.eigh(-casdm1)
    occ = -occ
    log.info('Natural occ %s', str(occ))
# restore phase
    for i, k in enumerate(numpy.argmax(abs(ucas), axis=0)):
        if ucas[k,i] < 0:
            ucas[:,i] *= -1
    mo_coeff1 = mo_coeff.copy()
    mo_coeff1[:,ncore:nocc] = numpy.dot(mo_coeff[:,ncore:nocc], ucas)

# where_natorb gives the location of the natural orbital for the input cas
# orbitals.  gen_strings4orblist map thes sorted strings (on CAS orbital) to
# the unsorted determinant strings (on natural orbital). e.g.  (3o,2e) system
#       CAS orbital      1  2  3
#       natural orbital  3  1  2        <= by mo_1to1map
#       CASorb-strings   0b011, 0b101, 0b110
#                    ==  (1,2), (1,3), (2,3) 
#       natorb-strings   (3,1), (3,2), (1,2)
#                    ==  0B101, 0B110, 0B011    <= by gen_strings4orblist
# then argsort to translate the string representation to the address
#       [2(=0B011), 0(=0B101), 1(=0B110)]
# to indicate which CASorb-strings address to be loaded in each natorb-strings slot
    where_natorb = mo_1to1map(ucas)
    guide_stringsa = fci.cistring.gen_strings4orblist(where_natorb, nelecas[0])
    guide_stringsb = fci.cistring.gen_strings4orblist(where_natorb, nelecas[1])
    old_det_idxa = numpy.argsort(guide_stringsa)
    old_det_idxb = numpy.argsort(guide_stringsb)

    h1eff =(reduce(numpy.dot, (mo_coeff[:,ncore:nocc].T, mc.get_hcore(),
                               mo_coeff[:,ncore:nocc]))
          + eris.vhf_c[ncore:nocc,ncore:nocc])
    h1eff = reduce(numpy.dot, (ucas.T, h1eff, ucas))
    aaaa = eris.aapp[:,:,ncore:nocc,ncore:nocc].copy()
    aaaa = ao2mo.incore.full(ao2mo.restore(8, aaaa, ncas), ucas)
    e_cas, fcivec = mc.fcisolver.kernel(h1eff, aaaa, ncas, nelecas,
                                        ci0=ci[old_det_idxa[:,None],old_det_idxb])
    log.debug('In Natural orbital, CI energy = %.12g', e_cas)
    return mo_coeff1, fcivec, occ

def canonicalize(mc, mo_coeff=None, ci=None, eris=None, verbose=None):
    mo_coeff, fcivec = cas_natorb(mc, mo_coeff, ci, eris, verbose=verbose)[:2]
    return mo_coeff, fcivec


def kernel(casci, mo_coeff=None, ci0=None, verbose=None, **cikwargs):
    '''CASCI solver
    '''
    if verbose is None: verbose = casci.verbose
    if mo_coeff is None: mo_coeff = casci.mo_coeff
    log = pyscf.lib.logger.Logger(casci.stdout, verbose)
    t0 = (time.clock(), time.time())
    log.debug('Start CASCI')

    ncas = casci.ncas
    nelecas = casci.nelecas
    ncore = casci.ncore
    mo_core, mo_cas, mo_vir = extract_orbs(mo_coeff, ncas, nelecas, ncore)

    # 1e
    h1eff, energy_core = casci.h1e_for_cas(mo_coeff)
    t1 = log.timer('effective h1e in CAS space', *t0)

    # 2e
    eri_cas = casci.ao2mo(mo_cas)
    t1 = log.timer('integral transformation to CAS space', *t1)

    # FCI
    e_cas, fcivec = casci.fcisolver.kernel(h1eff, eri_cas, ncas, nelecas,
                                           ci0=ci0, **cikwargs)

    t1 = log.timer('FCI solver', *t1)
    e_tot = e_cas + energy_core + casci.mol.energy_nuc()
    log.note('CASCI E = %.15g, E(CI) = %.15g', e_tot, e_cas)
    log.timer('CASCI', *t0)
    return e_tot, e_cas, fcivec


class CASCI(object):
    '''CASCI

    Attributes:
        verbose : int
            Print level.  Default value equals to :class:`Mole.verbose`.
        max_memory : float or int
            Allowed memory in MB.  Default value equals to :class:`Mole.max_memory`.
        ncas : int
            Active space size.
        nelecas : tuple of int
            Active (nelec_alpha, nelec_beta)
        ncore : int or tuple of int
            Core electron number.  In UHF-CASSCF, it's a tuple to indicate the different core eletron numbers.
        fcisolver : an instance of :class:`FCISolver`
            The pyscf.fci module provides several FCISolver for different scenario.  Generally,
            fci.direct_spin1.FCISolver can be used for all RHF-CASSCF.  However, a proper FCISolver
            can provide better performance and better numerical stability.  One can either use
            :func:`fci.solver` function to pick the FCISolver by the program or manually assigen
            the FCISolver to this attribute, e.g.

            >>> from pyscf import fci
            >>> mc = mcscf.CASSCF(mf, 4, 4)
            >>> mc.fcisolver = fci.solver(mol, singlet=True)
            >>> mc.fcisolver = fci.direct_spin1.FCISolver(mol)

            You can control FCISolver by setting e.g.::

                >>> mc.fcisolver.max_cycle = 30
                >>> mc.fcisolver.conv_tol = 1e-7

            For more details of the parameter for FCISolver, See :mod:`fci`.

    Saved results

        e_tot : float
            Total MCSCF energy (electronic energy plus nuclear repulsion)
        ci : ndarray
            CAS space FCI coefficients

    Examples:

    >>> from pyscf import gto, scf, mcscf
    >>> mol = gto.M(atom='N 0 0 0; N 0 0 1', basis='ccpvdz', verbose=0)
    >>> mf = scf.RHF(mol)
    >>> mf.scf()
    >>> mc = mcscf.CASCI(mf, 6, 6)
    >>> mc.kernel()[0]
    -108.980200816243354
    '''
    def __init__(self, mf, ncas, nelecas, ncore=None):
        mol = mf.mol
        self.mol = mol
        self._scf = mf
        self.verbose = mol.verbose
        self.stdout = mol.stdout
        self.max_memory = mf.max_memory
        self.ncas = ncas
        if isinstance(nelecas, (int, numpy.integer)):
            assert(nelecas%2 == 0)
            nelecb = (nelecas-mol.spin)//2
            neleca = nelecas - nelecb
            self.nelecas = (neleca, nelecb)
        else:
            self.nelecas = (nelecas[0],nelecas[1])
        if ncore is None:
            ncorelec = mol.nelectron - (self.nelecas[0]+self.nelecas[1])
            assert(ncorelec % 2 == 0)
            self.ncore = ncorelec // 2
        else:
            assert(isinstance(ncore, (int, numpy.integer)))
            self.ncore = ncore
        #self.fcisolver = fci.direct_spin0.FCISolver(mol)
        self.fcisolver = fci.solver(mol, self.nelecas[0]==self.nelecas[1])
# CI solver parameters are set in fcisolver object
        self.fcisolver.lindep = 1e-10
        self.fcisolver.max_cycle = 50
        self.fcisolver.conv_tol = 1e-8

##################################################
# don't modify the following attributes, they are not input options
        self.mo_coeff = mf.mo_coeff
        self.ci = None
        self.e_tot = 0

        self._keys = set(self.__dict__.keys())

    def dump_flags(self):
        log = pyscf.lib.logger.Logger(self.stdout, self.verbose)
        log.info('')
        log.info('******** CASCI flags ********')
        nvir = self.mo_coeff.shape[1] - self.ncore - self.ncas
        log.info('CAS (%de+%de, %do), ncore = %d, nvir = %d', \
                 self.nelecas[0], self.nelecas[1], self.ncas, self.ncore, nvir)
        log.info('max_memory %d (MB)', self.max_memory)
        try:
            self.fcisolver.dump_flags(self.verbose)
        except:
            pass

    def get_hcore(self, mol=None):
        return self._scf.get_hcore(mol)

    def get_veff(self, mol=None, dm=None, hermi=1):
        if mol is None: mol = self.mol
        if dm is None:
            mocore = self.mo_coeff[:,:self.ncore]
            dm = numpy.dot(mocore, mocore.T) * 2
# don't call self._scf.get_veff, because ROHF return alpha,beta potential separately
        vj, vk = self._scf.get_jk(mol, dm, hermi=hermi)
        return vj - vk * .5

    def get_h2cas(self, mo_coeff=None):
        return self.ao2mo(self, mo_coeff)
    def get_h2eff(self, mo_coeff=None):
        return self.ao2mo(self, mo_coeff)
    def ao2mo(self, mo_coeff=None):
        if mo_coeff is None:
            mo_coeff = self.mo_coeff[:,self.ncore:self.ncore+self.ncas]
        nao, nmo = mo_coeff.shape
        if self._scf._eri is not None and \
           (nao**2*nmo**2+nmo**4*2+self._scf._eri.size)*8/1e6 < self.max_memory*.95:
            eri = pyscf.ao2mo.incore.full(self._scf._eri, mo_coeff)
        else:
            eri = pyscf.ao2mo.outcore.full_iofree(self.mol, mo_coeff,
                                                  verbose=self.verbose)
        return eri

    def get_h1cas(self, mo_coeff=None, ncas=None, ncore=None):
        return self.h1e_for_cas(mo_coeff, ncas, ncore)
    def get_h1eff(self, mo_coeff=None, ncas=None, ncore=None):
        return self.h1e_for_cas(mo_coeff, ncas, ncore)
    def h1e_for_cas(self, mo_coeff=None, ncas=None, ncore=None):
        if mo_coeff is None: mo_coeff = self.mo_coeff
        return h1e_for_cas(self, mo_coeff, ncas, ncore)

    def kernel(self, *args, **kwargs):
        return self.casci(*args, **kwargs)
    def casci(self, mo_coeff=None, ci0=None, **cikwargs):
        if mo_coeff is None:
            mo_coeff = self.mo_coeff
        else:
            self.mo_coeff = mo_coeff
        if ci0 is None:
            ci0 = self.ci

        self.mol.check_sanity(self)

        self.dump_flags()

        self.e_tot, e_cas, self.ci = \
                kernel(self, mo_coeff, ci0=ci0, verbose=self.verbose, **cikwargs)
        return self.e_tot, e_cas, self.ci

    def cas_natorb(self, mo_coeff=None, ci=None, eris=None, verbose=None):
        return cas_natorb(self, mo_coeff, ci, eris, verbose)
    def cas_natorb_(self, mo_coeff=None, ci=None, eris=None, verbose=None):
        self.mo_coeff, self.ci, occ = cas_natorb(self, mo_coeff, ci, eris, verbose)
        return self.ci, self.mo_coeff

    def get_fock(self, mo_coeff=None, ci=None, eris=None, verbose=None):
        return get_fock(self, mo_coeff, ci, eris, verbose)

    def canonicalize(self, mo_coeff=None, ci=None, eris=None, verbose=None):
        return canonicalize(self, mo_coeff, ci, eris, verbose=verbose)
    def canonicalize_(self, mo_coeff=None, ci=None, eris=None, verbose=None):
        self.mo_coeff, self.ci = canonicalize(self, mo_coeff, ci, eris,
                                              verbose=verbose)
        return self.mo_coeff, self.ci

    def analyze(self, mo_coeff=None, ci=None):
        log = logger.Logger(self.stdout, self.verbose)
        return analyze(self, mo_coeff, ci, verbose=log)



if __name__ == '__main__':
    from pyscf import gto
    from pyscf import scf
    mol = gto.Mole()
    mol.verbose = 0
    mol.output = None#"out_h2o"
    mol.atom = [
        ['O', ( 0., 0.    , 0.   )],
        ['H', ( 0., -0.757, 0.587)],
        ['H', ( 0., 0.757 , 0.587)],]

    mol.basis = {'H': 'sto-3g',
                 'O': '6-31g',}
    mol.build()

    m = scf.RHF(mol)
    ehf = m.scf()
    mc = CASCI(m, 4, 4)
    mc.fcisolver = fci.solver(mol)
    emc = mc.casci()[0]
    print(ehf, emc, emc-ehf)
    #-75.9577817425 -75.9624554777 -0.00467373522233
    print(emc+75.9624554777)

    mc = CASCI(m, 4, (3,1))
    #mc.fcisolver = fci.direct_spin1
    mc.fcisolver = fci.solver(mol, False)
    emc = mc.casci()[0]
    print(emc - -75.439016172976)

    mol = gto.Mole()
    mol.verbose = 0
    mol.output = "out_casci"
    mol.atom = [
        ["C", (-0.65830719,  0.61123287, -0.00800148)],
        ["C", ( 0.73685281,  0.61123287, -0.00800148)],
        ["C", ( 1.43439081,  1.81898387, -0.00800148)],
        ["C", ( 0.73673681,  3.02749287, -0.00920048)],
        ["C", (-0.65808819,  3.02741487, -0.00967948)],
        ["C", (-1.35568919,  1.81920887, -0.00868348)],
        ["H", (-1.20806619, -0.34108413, -0.00755148)],
        ["H", ( 1.28636081, -0.34128013, -0.00668648)],
        ["H", ( 2.53407081,  1.81906387, -0.00736748)],
        ["H", ( 1.28693681,  3.97963587, -0.00925948)],
        ["H", (-1.20821019,  3.97969587, -0.01063248)],
        ["H", (-2.45529319,  1.81939187, -0.00886348)],]

    mol.basis = {'H': 'sto-3g',
                 'C': 'sto-3g',}
    mol.build()

    m = scf.RHF(mol)
    ehf = m.scf()
    mc = CASCI(m, 9, 8)
    mc.fcisolver = fci.solver(mol)
    emc = mc.casci()[0]
    print(ehf, emc, emc-ehf)
    print(emc - -227.948912536)

    mc = CASCI(m, 9, (5,3))
    #mc.fcisolver = fci.direct_spin1
    mc.fcisolver = fci.solver(mol, False)
    emc = mc.casci()[0]
    print(emc - -227.7674519720)