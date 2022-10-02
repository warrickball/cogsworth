import time
import os
from copy import copy
from multiprocessing import Pool
import numpy as np
import astropy.units as u
import astropy.coordinates as coords
import h5py as h5
import pandas as pd

from cosmic.sample.initialbinarytable import InitialBinaryTable
from cosmic.evolve import Evolve
import gala.potential as gp
import gala.dynamics as gd

from kicker import galaxy
from kicker.kicks import integrate_orbit_with_events
from kicker.events import identify_events
from kicker.classify import determine_final_classes
from kicker.observables import get_phot


class Population():
    """Class for creating and evolving populations of binaries throughout the Milky Way

    Parameters
    ----------
    n_binaries : `int`
        How many binaries to sample for the population
    processes : `int`, optional
        How many processes to run if you want multithreading, by default 8
    m1_cutoff : `float`, optional
        The minimum allowed primary mass, by default 7
    final_kstar1 : `list`, optional
        Desired final types for primary star, by default list(range(14))
    final_kstar2 : `list`, optional
        Desired final types for secondary star, by default list(range(14))
    galaxy_model : `kicker.galaxy.Galaxy`, optional
        A Galaxy class to use for sampling the initial galaxy parameters, by default kicker.galaxy.Frankel2018
    galactic_potential : `gala.potential.PotentialBase`, optional
        Galactic potential to use for evolving the orbits of binaries, by default gp.MilkyWayPotential()
    v_dispersion : `float`, optional
        Velocity dispersion to apply relative to the local circular velocity, by default 5*u.km/u.s
    max_ev_time : `float`, optional
        Maximum evolution time for both COSMIC and Gala, by default 12.0*u.Gyr
    timestep_size : `float`, optional
        Size of timesteps to use in galactic evolution, by default 1*u.Myr
    BSE_settings : `dict`, optional
        Any BSE settings to pass to COSMIC

    Attributes
    ----------
    mass_singles : `float`
        Total mass in single stars needed to generate population
    mass_binaries : `float`
        Total mass in binaries needed to generate population
    n_singles_req : `int`
        Number of single stars needed to generate population
    n_bin_req : `int`
        Number of binaries needed to generate population
    bpp : `pandas.DataFrame`
        Evolutionary history of each binary
    bcm : `pandas.DataFrame`
        Final state of each binary
    initC : `pandas.DataFrame`
        Initial conditions for each binary
    kick_info : `pandas.DataFrame`
        Information about the kicks that occur for each binary
    orbits : `list of gala.dynamics.Orbit`
        The orbits of each binary within the galaxy from its birth until `self.max_ev_time` with timesteps of
        `self.timestep_size`. Note that disrupted binaries will have two entries (for both stars).
    classes : `list`
        The classes associated with each produced binary (see classify.list_classes for a list of available
        classes and their meanings)
    final_coords : `tuple of Astropy SkyCoord`
        A SkyCoord object of the final positions of each binary in the galactocentric frame.
        For bound binaries only the first SkyCoord is populated, for disrupted binaries each SkyCoord
        corresponds to the individual components. Any missing orbits (where orbit=None or there is no
        secondary component) will be set to `np.inf` for ease of masking.
    final_bpp : `pandas.DataFrame`
        The final state of each binary (taken from the final entry in `self.bpp`)
    observables : `pandas.DataFrame`
        Observables associated with the final binaries. See `get_observables` for more details on the columns
    """
    def __init__(self, n_binaries, processes=8, m1_cutoff=7, final_kstar1=list(range(14)),
                 final_kstar2=list(range(14)), galaxy_model=galaxy.Frankel2018,
                 galactic_potential=gp.MilkyWayPotential(), v_dispersion=5 * u.km / u.s,
                 max_ev_time=12.0*u.Gyr, timestep_size=1 * u.Myr, BSE_settings={}):
        self.n_binaries = n_binaries
        self.n_binaries_match = n_binaries
        self.processes = processes
        self.m1_cutoff = m1_cutoff
        self.final_kstar1 = final_kstar1
        self.final_kstar2 = final_kstar2
        self.galaxy_model = galaxy_model
        self.galactic_potential = galactic_potential
        self.v_dispersion = v_dispersion
        self.max_ev_time = max_ev_time
        self.timestep_size = timestep_size
        self.pool = None

        self._initial_binaries = None
        self._mass_singles = None
        self._mass_binaries = None
        self._n_singles_req = None
        self._n_bin_req = None
        self._bpp = None
        self._bcm = None
        self._initC = None
        self._kick_info = None
        self._orbits = None
        self._classes = None
        self._final_coords = None
        self._final_bpp = None
        self._observables = None

        # TODO: give users access to changing these settings
        self.BSE_settings = {'xi': 1.0, 'bhflag': 1, 'neta': 0.5, 'windflag': 3, 'wdflag': 1, 'alpha1': 1.0,
                             'pts1': 0.001, 'pts3': 0.02, 'pts2': 0.01, 'epsnov': 0.001, 'hewind': 0.5,
                             'ck': 1000, 'bwind': 0.0, 'lambdaf': 0.0, 'mxns': 3.0, 'beta': -1.0, 'tflag': 1,
                             'acc2': 1.5, 'grflag': 1, 'remnantflag': 4, 'ceflag': 0, 'eddfac': 1.0,
                             'ifflag': 0, 'bconst': 3000, 'sigma': 265.0, 'gamma': -2.0, 'pisn': 45.0,
                             'natal_kick_array': [[-100.0, -100.0, -100.0, -100.0, 0.0],
                                                  [-100.0, -100.0, -100.0, -100.0, 0.0]], 'bhsigmafrac': 1.0,
                             'polar_kick_angle': 90, 'qcrit_array': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                                                     0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                             'cekickflag': 2, 'cehestarflag': 0, 'cemergeflag': 0, 'ecsn': 2.25,
                             'ecsn_mlow': 1.6, 'aic': 1, 'ussn': 0, 'sigmadiv': -20.0, 'qcflag': 5,
                             'eddlimflag': 0, 'fprimc_array': [2.0/21.0, 2.0/21.0, 2.0/21.0, 2.0/21.0,
                                                               2.0/21.0, 2.0/21.0, 2.0/21.0, 2.0/21.0,
                                                               2.0/21.0, 2.0/21.0, 2.0/21.0, 2.0/21.0,
                                                               2.0/21.0, 2.0/21.0, 2.0/21.0, 2.0/21.0],
                             'bhspinflag': 0, 'bhspinmag': 0.0, 'rejuv_fac': 1.0, 'rejuvflag': 0, 'htpmb': 1,
                             'ST_cr': 1, 'ST_tide': 1, 'bdecayfac': 1, 'rembar_massloss': 0.5, 'kickflag': 0,
                             'zsun': 0.014, 'bhms_coll_flag': 0, 'don_lim': -1, 'acc_lim': -1, 'binfrac': 0.5}
        self.BSE_settings.update(BSE_settings)

    @property
    def mass_singles(self):
        if self._mass_singles is None:
            self.sample_initial_binaries()
        return self._mass_singles

    @property
    def mass_binaries(self):
        if self._mass_binaries is None:
            self.sample_initial_binaries()
        return self._mass_binaries

    @property
    def n_singles_req(self):
        if self._n_singles_req is None:
            self.sample_initial_binaries()
        return self._n_singles_req

    @property
    def n_bin_req(self):
        if self._n_bin_req is None:
            self.sample_initial_binaries()
        return self._n_bin_req

    @property
    def bpp(self):
        if self._bpp is None:
            self.perform_stellar_evolution()
        return self._bpp

    @property
    def bcm(self):
        if self._bcm is None:
            self.perform_stellar_evolution()
        return self._bcm

    @property
    def initC(self):
        if self._initC is None:
            self.perform_stellar_evolution()
        return self._initC

    @property
    def kick_info(self):
        if self._kick_info is None:
            self.perform_stellar_evolution()
        return self._kick_info

    @property
    def orbits(self):
        if self._orbits is None:
            self.perform_galactic_evolution()
        return self._orbits

    @property
    def classes(self):
        if self._classes is None:
            self._classes = determine_final_classes(population=self)
        return self._classes

    @property
    def final_coords(self):
        if self._final_coords is None:
            self._final_coords = self.get_final_coords()
        return self._final_coords

    @property
    def final_bpp(self):
        if self._final_bpp is None:
            self._final_bpp = self.bpp.drop_duplicates(subset="bin_num", keep="last")
            self._final_bpp.insert(len(self._final_bpp.columns), "metallicity",
                                   self.initC["metallicity"].values)
        return self._final_bpp

    @property
    def observables(self):
        if self._observables is None:
            self._observables = self.get_observables()
        return self._observables

    def create_population(self, with_timing=True):
        """Create an entirely evolved population of binaries.

        This will sample the initial binaries and initial galaxy and then 
        perform both the COSMIC and Gala evolution

        Parameters
        ----------
        with_timing : `bool`, optional
            Whether to print messages about the timing, by default True
        """
        if with_timing:
            start = time.time()
            print(f"Run for {self.n_binaries} binaries")

        self.sample_initial_binaries()
        if with_timing:
            print(f"Ended up with {self.n_binaries_match} binaries with masses > {self.m1_cutoff} solar masses")
            print(f"[{time.time() - start:1.0e}s] Sample initial binaries")
            lap = time.time()

        self.pool = Pool(self.processes) if self.processes else None
        self.perform_stellar_evolution()
        if with_timing:
            print(f"[{time.time() - lap:1.1f}s] Evolve binaries (run COSMIC)")
            lap = time.time()

        self.perform_galactic_evolution()
        if with_timing:
            print(f"[{time.time() - lap:1.1f}s] Get orbits (run gala)")

        if self.pool is not None:
            self.pool.close()
            self.pool.join()
            self.pool = None

        if with_timing:
            print(f"Overall: {time.time() - start:1.1f}s")

    def sample_initial_binaries(self):
        """Sample the initial binary parameters for the population"""
        self._initial_binaries, self._mass_singles, self._mass_binaries, self._n_singles_req,\
            self._n_bin_req = InitialBinaryTable.sampler('independent', self.final_kstar1, self.final_kstar2,
                                                         binfrac_model=self.BSE_settings["binfrac"],
                                                         primary_model='kroupa01', ecc_model='sana12',
                                                         porb_model='sana12', qmin=-1,
                                                         SF_start=self.max_ev_time.to(u.Myr).value,
                                                         SF_duration=0.0, met=0.02, size=self.n_binaries)

        # apply the mass cutoff
        self._initial_binaries = self._initial_binaries[self._initial_binaries["mass_1"] >= self.m1_cutoff]

        # count how many binaries actually match the criteria (may be larger than `n_binaries` due to sampler)
        self.n_binaries_match = len(self._initial_binaries)

        # initialise the initial galaxy class with correct number of binaries
        self.initial_galaxy = self.galaxy_model(size=self.n_binaries_match)

        # work out the initial velocities of each binary
        vel_units = u.km / u.s

        # calculate the Galactic circular velocity at the initial positions
        v_circ = self.galactic_potential.circular_velocity(q=[self.initial_galaxy.x,
                                                              self.initial_galaxy.y,
                                                              self.initial_galaxy.z]).to(vel_units)

        # add some velocity dispersion
        v_R, v_T, v_z = np.random.normal([np.zeros_like(v_circ), v_circ, np.zeros_like(v_circ)],
                                         self.v_dispersion.to(vel_units) / np.sqrt(3),
                                         size=(3, self.n_binaries_match))
        v_R, v_T, v_z = v_R * vel_units, v_T * vel_units, v_z * vel_units
        self.initial_galaxy.v_R = v_R
        self.initial_galaxy.v_T = v_T
        self.initial_galaxy.v_z = v_z

        # update the metallicity and birth times of the binaries to match the galaxy
        self._initial_binaries["metallicity"] = self.initial_galaxy.Z
        self._initial_binaries["tphysf"] = self.initial_galaxy.tau.to(u.Myr).value

        # ensure metallicities remain in a range valid for COSMIC - original value still in initial_galaxy.Z
        self._initial_binaries["metallicity"][self._initial_binaries["metallicity"] < 1e-4] = 1e-4
        self._initial_binaries["metallicity"][self._initial_binaries["metallicity"] > 0.03] = 0.03

    def perform_stellar_evolution(self):
        """Perform the (binary) stellar evolution of the sampled binaries"""
        # delete any cached variables
        self._final_bpp = None
        self._observables = None

        if self._initial_binaries is None and self._initC is None:
            print("Warning: Initial binaries not yet sampled, performing sampling now.")
            self.sample_initial_binaries()
        elif self._initial_binaries is None:
            self._initial_binaries = self._initC

        no_pool_existed = self.pool is None and self.processes > 1
        if no_pool_existed:
            self.pool = Pool(self.processes)

        self._bpp, self._bcm, self._initC,\
            self._kick_info = Evolve.evolve(initialbinarytable=self._initial_binaries,
                                            BSEDict=self.BSE_settings, pool=self.pool)

        if no_pool_existed:
            self.pool.close()
            self.pool.join()

        # check if there are any NaNs in the final bpp table rows or the kick_info
        final_bpp = self._bpp[~self._bpp.index.duplicated(keep="last")]
        nans = np.isnan(final_bpp["sep"])
        kick_info_nans = np.isnan(self._kick_info["delta_vsysx_1"])

        # if we detect NaNs
        if nans.any() or kick_info_nans.any():
            # make sure the user knows bad things have happened
            print("WARNING! PANIC! THE SKY THE FALLING!")
            print("------------------------------------")
            print("(NaNs detected)")

            # store the bad things for later
            nan_bin_nums = np.concatenate((final_bpp[nans]["bin_num"].values,
                                           self._kick_info[kick_info_nans]["bin_num"].values))
            self._bpp[self._bpp["bin_num"].isin(nan_bin_nums)].to_hdf("nans.h5", key="bpp")
            self._initC[self._initC["bin_num"].isin(nan_bin_nums)].to_hdf("nans.h5", key="initC")
            self._kick_info[self._kick_info["bin_num"].isin(nan_bin_nums)].to_hdf("nans.h5", key="kick_info")

            # update the population to delete any bad binaries
            n_nan = len(nan_bin_nums)
            self.n_binaries_match -= n_nan
            self._bpp = self._bpp[~self._bpp["bin_num"].isin(nan_bin_nums)]
            self._bcm = self._bcm[~self._bcm["bin_num"].isin(nan_bin_nums)]
            self._kick_info = self._kick_info[~self._kick_info["bin_num"].isin(nan_bin_nums)]
            self._initC = self._initC[~self._initC["bin_num"].isin(nan_bin_nums)]

            not_nan = ~final_bpp["bin_num"].isin(nan_bin_nums)
            self.initial_galaxy._tau = self.initial_galaxy._tau[not_nan]
            self.initial_galaxy._Z = self.initial_galaxy._Z[not_nan]
            self.initial_galaxy._z = self.initial_galaxy._z[not_nan]
            self.initial_galaxy._rho = self.initial_galaxy._rho[not_nan]
            self.initial_galaxy._phi = self.initial_galaxy._phi[not_nan]
            self.initial_galaxy.v_R = self.initial_galaxy.v_R[not_nan]
            self.initial_galaxy.v_T = self.initial_galaxy.v_T[not_nan]
            self.initial_galaxy.v_z = self.initial_galaxy.v_z[not_nan]
            self.initial_galaxy._x = self.initial_galaxy._x[not_nan]
            self.initial_galaxy._y = self.initial_galaxy._y[not_nan]
            self.initial_galaxy._which_comp = self.initial_galaxy._which_comp[not_nan]
            self.initial_galaxy._size -= n_nan

            print(f"WARNING: {n_nan} bad binaries removed from tables - but normalisation may be off")
            print("I've added the offending binaries to the `nan.h5` file, do with them what you will")

    def perform_galactic_evolution(self):
        # delete any cached variables
        self._final_coords = None
        self._observables = None

        # turn the drawn coordinates into an astropy representation
        rep = coords.CylindricalRepresentation(self.initial_galaxy.rho,
                                               self.initial_galaxy.phi,
                                               self.initial_galaxy.z)

        # create differentials based on the velocities (dimensionless angles allows radians conversion)
        with u.set_enabled_equivalencies(u.dimensionless_angles()):
            dif = coords.CylindricalDifferential(self.initial_galaxy.v_R,
                                                 (self.initial_galaxy.v_T
                                                  / self.initial_galaxy.rho).to(u.rad / u.Gyr),
                                                 self.initial_galaxy.v_z)

        # combine the representation and differentials into a Gala PhaseSpacePosition
        w0s = gd.PhaseSpacePosition(rep.with_differentials(dif))

        # identify the pertinent events in the evolution
        events = identify_events(full_bpp=self.bpp, full_kick_info=self.kick_info)

        # if we want to use multiprocessing
        if self.pool is not None or self.processes > 1:
            # track whether a pool already existed
            pool_existed = self.pool is not None

            # if not, create one
            if not pool_existed:
                self.pool = Pool(self.processes)

            # setup arguments and evolve the orbits from birth until present day
            args = [(w0s[i], self.galactic_potential, events[i],
                     self.max_ev_time - self.initial_galaxy.tau[i], self.max_ev_time,
                     copy(self.timestep_size)) for i in range(self.n_binaries_match)]
            orbits = self.pool.starmap(integrate_orbit_with_events, args)

            # if a pool didn't exist before then close the one just created
            if not pool_existed:
                self.pool.close()
                self.pool.join()
        else:
            # otherwise just use a for loop to evolve the orbits from birth until present day
            orbits = []
            for i in range(self.n_binaries_match):
                orbits.append(integrate_orbit_with_events(w0=w0s[i], potential=self.galactic_potential,
                                                          events=events[i],
                                                          t1=self.max_ev_time - self.initial_galaxy.tau[i],
                                                          t2=self.max_ev_time, dt=copy(self.timestep_size)))

        self._orbits = np.array(orbits, dtype="object")

    def get_final_coords(self):
        """Get the final coordinates of each binary (or each component in disrupted binaries)

        Returns
        -------
        final_coords : `tuple of Astropy SkyCoords`
            A SkyCoord object of the final positions of each binary in the galactocentric frame.
            For bound binaries only the first SkyCoord is populated, for disrupted binaries each SkyCoord
            corresponds to the individual components. Any missing orbits (where orbit=None or there is no
            secondary component) will be set to `np.inf` for ease of masking.
        """
        # pool all of the orbits into a single numpy array
        final_kinematics = np.ones((len(self.orbits), 2, 6)) * np.inf
        for i, orbit in enumerate(self.orbits):
            # check if the orbit is missing
            if orbit is None:
                print("Warning: Detected `None` orbit, entering coordinates as `np.inf`")

            # check if it has been disrupted
            elif isinstance(orbit, list):
                final_kinematics[i, 0, :3] = orbit[0][-1].pos.xyz.to(u.kpc).value
                final_kinematics[i, 1, :3] = orbit[1][-1].pos.xyz.to(u.kpc).value
                final_kinematics[i, 0, 3:] = orbit[0][-1].vel.d_xyz.to(u.km / u.s)
                final_kinematics[i, 1, 3:] = orbit[1][-1].vel.d_xyz.to(u.km / u.s)

            # otherwise just save the system in the primary
            else:
                final_kinematics[i, 0, :3] = orbit[-1].pos.xyz.to(u.kpc).value
                final_kinematics[i, 0, 3:] = orbit[-1].vel.d_xyz.to(u.km / u.s)

        # turn the array into two SkyCoords
        final_coords = [coords.SkyCoord(x=final_kinematics[:, i, 0] * u.kpc,
                                        y=final_kinematics[:, i, 1] * u.kpc,
                                        z=final_kinematics[:, i, 2] * u.kpc,
                                        v_x=final_kinematics[:, i, 3] * u.km / u.s,
                                        v_y=final_kinematics[:, i, 4] * u.km / u.s,
                                        v_z=final_kinematics[:, i, 5] * u.km / u.s,
                                        frame="galactocentric") for i in [0, 1]]
        return final_coords[0], final_coords[1]

    def get_observables(self, filters=['J', 'H', 'K', 'G', 'BP', 'RP']):
        """Get observables associated with the binaries at present day.

        These include: extinction due to dust, absolute and apparent bolometric magnitudes for each star,
        apparent magnitudes in each filter and observed temperature and surface gravity for each binary.

        For bound binaries and stellar mergers, only the column `{filter}_app_1` is relevant. For
        disrupted binaries, `{filter}_app_1` is for the primary star and `{filter}_app_2` is for
        the secondary star.

        Parameters
        ----------
        filters : `list`, optional
            Which filters to compute observables for, by default ['J', 'H', 'K', 'G', 'BP', 'RP']
        """
        return get_phot(self.final_bpp, self.final_coords, filters)

    def save(self, file_name, overwrite=False):
        """Save a Population to disk

        This will produce 4 files:
            - An HDF5 file containing most of the data
            - A .npy file containing the orbits
            - A .txt file detailing the Galactic potential used
            - A .txt file detailing the initial galaxy model used

        Parameters
        ----------
        file_name : `str`
            A file name to use. Either no file extension or ".h5".
        overwrite : `bool`, optional
            Whether to overwrite any existing files, by default False

        Raises
        ------
        FileExistsError
            If `overwrite=False` and files already exist
        """
        if file_name[-3:] != ".h5":
            file_name += ".h5"
        if os.path.isfile(file_name):
            if overwrite:
                os.remove(file_name)
            else:
                raise FileExistsError((f"{file_name} already exists. Set `overwrite=True` to overwrite "
                                       "the file."))
        self.bpp.to_hdf(file_name, key="bpp")
        self.bcm.to_hdf(file_name, key="bcm")
        self.initC.to_hdf(file_name, key="initC")
        self.kick_info.to_hdf(file_name, key="kick_info")

        self.galactic_potential.save(file_name.replace('.h5', '-potential.txt'))
        self.initial_galaxy.save(file_name, key="initial_galaxy")
        np.save(file_name.replace(".h5", "-orbits.npy"), np.array(self.orbits, dtype="object"))

        with h5.File(file_name, "a") as file:
            numeric_params = np.array([self.n_binaries, self.n_binaries_match, self.processes, self.m1_cutoff,
                                       self.v_dispersion.to(u.km / u.s).value,
                                       self.max_ev_time.to(u.Gyr).value, self.timestep_size.to(u.Myr).value,
                                       self.mass_singles, self.mass_binaries, self.n_singles_req,
                                       self.n_bin_req])
            file.create_dataset("numeric_params", data=numeric_params)

            k_stars = np.array([self.final_kstar1, self.final_kstar2])
            file.create_dataset("k_stars", data=k_stars)

            # save BSE settings
            d = file.create_dataset("BSE_settings", data=[])
            for key in self.BSE_settings:
                d.attrs[key] = self.BSE_settings[key]


def load(file_name):
    """Load a Population from a series of files

    Parameters
    ----------
    file_name : `str`
        Base name of the files to use. Should either have no file extension or ".h5"

    Returns
    -------
    pop : `Population`
        The loaded Population
    """
    if file_name[-3:] != ".h5":
        file_name += ".h5"

    BSE_settings = {}
    with h5.File(file_name, "r") as file:
        numeric_params = file["numeric_params"][...]
        k_stars = file["k_stars"][...]

        # load in BSE settings
        for key in file["BSE_settings"].attrs:
            BSE_settings[key] = file["BSE_settings"].attrs[key]

    initial_galaxy = galaxy.load(file_name, key="initial_galaxy")
    galactic_potential = gp.potential.load(file_name.replace('.h5', '-potential.txt'))

    p = Population(n_binaries=int(numeric_params[0]), processes=int(numeric_params[2]),
                   m1_cutoff=numeric_params[3], final_kstar1=k_stars[0], final_kstar2=k_stars[1],
                   galaxy_model=initial_galaxy.__class__, galactic_potential=galactic_potential,
                   v_dispersion=numeric_params[4] * u.km / u.s, max_ev_time=numeric_params[5] * u.Gyr,
                   timestep_size=numeric_params[6] * u.Myr, BSE_settings=BSE_settings)

    p.n_binaries_match = int(numeric_params[1])
    p._mass_singles = numeric_params[7]
    p._mass_binaries = numeric_params[8]
    p._n_singles_req = numeric_params[9]
    p._n_bin_req = numeric_params[10]

    p.initial_galaxy = initial_galaxy

    p._bpp = pd.read_hdf(file_name, key="bpp")
    p._bcm = pd.read_hdf(file_name, key="bcm")
    p._initC = pd.read_hdf(file_name, key="initC")
    p._kick_info = pd.read_hdf(file_name, key="kick_info")

    p._orbits = np.load(file_name.replace(".h5", "-orbits.npy"), allow_pickle=True)

    return p
