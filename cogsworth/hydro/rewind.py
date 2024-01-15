import numpy as np
import astropy.units as u
import pandas as pd
import gala.dynamics as gd
import gala.integrate as gi

from multiprocessing import Pool
from tqdm import tqdm
import warnings


def rewind_to_formation(subsnap, pot, dt=-1 * u.Myr, processes=1):
    """Rewind a snapshot to the time of formation of each particle

    Parameters
    ----------
    subsnap : :class:`pynbody.snapshot.SimSnap`
        A subset of a snapshot containing only the particles to rewind
    pot : :class:`gala.potential.potential.CompositePotential`
        The potential of the snapshot
    dt : :class:`~astropy.units.Quantity` [time], optional
        Timestep size, by default -1*u.Myr
    processes : `int`, optional
        How many processes to use, by default 1 (run single-threaded)

    Returns
    -------
    init_particles : :class:`~pandas.DataFrame`
        A dataframe containing the initial mass, metallicity, formation time,
        position and velocity of each particle
    """
    # get the final time of the snapshot in Myr
    final_time = subsnap.properties["time"].in_units("Myr") * u.Myr

    # define a function to integrate the orbit of a particle backwards in time
    def _tohspans(w0, t2):
        """tohspans = snapshot backwards in time lol"""
        return pot.integrate_orbit(w0, t1=final_time, t2=t2, dt=dt,
                                   Integrator=gi.DOPRI853Integrator, store_all=False)[-1]

    # convert the final particles to a phase-space position
    wf = gd.PhaseSpacePosition(pos=np.transpose(subsnap["pos"].in_units("kpc")) * u.kpc,
                               vel=np.transpose(subsnap["vel"].in_units("km s**-1")) * u.km / u.s)
    # store their formation times in Myr
    tforms = subsnap["tform"].in_units("Myr") * u.Myr

    # integrate the orbits of the particles backwards in time to their formation times
    # if the user wants to use multiple processes, do so
    if processes > 1:
        with Pool(processes) as pool:
            w0 = pool.starmap(_tohspans, tqdm(zip(wf, tforms), total=len(subsnap)))

    # otherwise, just do it single-threaded
    else:
        w0 = [_tohspans(wf[i], tforms[i]) for i in tqdm(range(len(subsnap)))]

    # check if the formation masses are available, warn if not
    if "massform" not in subsnap.all_keys():
        mass = subsnap["mass"].in_units("Msol")
        warnings.warn("Formation masses (`massform`) not found, using present day masses instead")
    else:
        mass = subsnap["massform"].in_units("Msol")

    # create a df of the initial particles and return
    init_particles = np.zeros((len(subsnap), 9))
    init_particles[:, 0] = mass
    init_particles[:, 1] = subsnap["metals"] if np.ndim(subsnap["metals"]) == 1 else subsnap["metals"][:, 0]
    init_particles[:, 2] = subsnap["tform"].in_units("Gyr")

    for i in range(len(w0)):
        init_particles[i, 3:6] = w0[i].xyz.to(u.kpc).value
        init_particles[i, 6:9] = w0[i].vel.d_xyz.to(u.km / u.s).value

    df = pd.DataFrame(init_particles, columns=["mass", "Z", "t_form", "x", "y", 'z', 'v_x', 'v_y', 'v_z'])
    return df
