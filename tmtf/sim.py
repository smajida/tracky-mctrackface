import os
import glob

import numpy as np
from scipy.ndimage import imread, gaussian_filter

from Antipasti.netdatautils import ctrax2np


__doc__ = """Fly Tracking Environment for Q-Learning."""


class Simulator(object):
    def __init__(self):
        pass

    def getstate(self):
        pass

    def getresponse(self, action):
        pass

    def setstate(self, state):
        pass

    def resetenv(self):
        pass


class FlySimulator(Simulator):
    def __init__(self, videoframes, track, actionresponse=None, rewardmetric=None, metatime=False, framesperstate=4,
                 episodelength=40):
        """
        :type videoframes: VideoFrames
        :param videoframes: Pre-parsed video frames.

        :type track: Track
        :param track: Pre-parsed tracks.

        :type actionresponse: callable
        :param actionresponse: Function returning the response for a given action, given the environment as an input.

        :type rewardmetric: callable
        :param rewardmetric: Function returning the reward given 'ist' (what it is) and 'soll' (what it should be)
                             values. German is a fun language.

        :type metatime: bool
        :param metatime: Whether to use (Steffen's) meta-time.

        :type framesperstate: int
        :param framesperstate: Number of previous frames to include in the state. 4 sounds like a good number.

        :type episodelength: int
        :param episodelength: Length of a training episode.
        """

        # Initialize superclass
        super(FlySimulator, self).__init__()

        # Assertions
        assert framesperstate >= 1, "Must have at least 1 frame per step."

        # Meta
        self.videoframes = videoframes
        self.framesperstate = framesperstate
        self.episodelength = episodelength
        self.track = track
        self.metatime = metatime

        # Default reward metric: rewarded if target is localized to within
        self.rewardmetric = lambda ist, soll: (np.linalg.norm(ist-soll) >= 5).astype('float') \
            if rewardmetric is None else rewardmetric

        # Make default action response function if none provided
        if actionresponse is None:
            self.actionresponse = lambda action: action_response_factory()(self, action)
        else:
            assert callable(actionresponse), "Action Response function must be callable."
            self.actionresponse = lambda action: actionresponse(self, action)

        # Internal dont-fuck-with-me attributes
        # Cross
        self._crosshair = None
        # Min global time
        self._minT = self.framesperstate - 1
        # Max global time
        self._maxT = self.videoframes.maxT
        # Training could occur in episodes which may not span the entire video sequence. In general, the tracking
        # problem doesn't define an episode (unlike in Atari games, where there's a game-start and game-over).
        # The environment should support arbitrary episodes as long as it's valid.
        self._episodeT = None
        self._episodestart = None
        self._episodestop = None

        self.imshape = self.videoframes.imshape

    @property
    def crosshair(self):
        return self._crosshair

    @crosshair.setter
    def crosshair(self, value):
        # Assertions on value
        # TODO
        # Set
        self._crosshair = value

    @property
    def episodeT(self):
        return self._episodeT

    @episodeT.setter
    def episodeT(self, value):
        assert value >= self._minT
        assert value <= self._maxT
        self._episodeT = value

    @property
    def state(self):
        return self.getstate()

    @property
    def reward(self):
        return self.getreward()

    def initepisode(self, episodestart, episodestop):
        """Initialize an episode."""

        # Inequality episodestop < self._maxT is due to the nature of how states are built.
        assert self._minT <= episodestart < episodestop < self._maxT

        # Set episode clock
        self.episodeT = self._episodestart = episodestart
        self._episodestop = episodestop
        # Read seed crosshair coordinates from track
        self.crosshair = self.track[self._episodestart]

    def getstate(self):
        # State is a 5 channel tensor:

        #     |    |     |     |     |
        #     |    |     |     |    >|
        # T = 1    0    -1    -2   Cross

        # Where t = 0 is the current frame (i.e. the position of the crosshair)

        # Fetch frames
        frames = self.videoframes.fetchframes(stop=(self.episodeT + 1), numsteps=self.framesperstate)
        # Fetch crosshair image
        crossimg = self.crosshair_image(imshape=self.imshape, coordinates=self.crosshair)
        # Concatenate frames and crossimg and add an extra (batch) dimension
        state = np.concatenate((frames, crossimg), axis=0)[None, ...]
        # Return
        return state

    def getreward(self, T=None):
        if T is None:
            T = self.episodeT
        # Get correct position
        correctpos = self.track[T]
        # Compute reward
        reward = self.rewardmetric(ist=self.crosshair, soll=correctpos)
        return reward

    def getresponse(self, action):
        # Action must be a tensor which, when squeezed, gives a one-hot vector.
        # Squeeze action
        action = action.squeeze().argmax()

        # Get response for an action
        reward, nextstate = self.actionresponse(action=action)

        # Return
        return reward, nextstate

    def isterminal(self):
        return self.episodeT == self._episodestop

    def resetenv(self):
        """Reset environment."""
        pass

    @staticmethod
    def crosshair_image(imshape, coordinates, smooth=0):
        """
        Function to make a zero image of shape `imshape`, place a white (one) pixel or a gaussian blob at the given
        `coordinates`.
        """
        # make CROSShair IMaGe
        crossimg = np.zeros(shape=imshape)
        # Place a pixel
        crossimg[coordinates] = 1.
        # Smooth if required to
        if smooth != 0:
            crossimg = gaussian_filter(crossimg, sigma=smooth)
        # Done
        return crossimg


class Track(object):
    """Class to wrap ctrax MATLAB file."""
    def __init__(self, matfilepath, objectid, roundcoordinates=True):
        """
        :type matfilepath: str
        :param matfilepath: Path to matlab file.

        :type objectid: int
        :param objectid: ID of the object being tracked.

        :type roundcoordinates: bool
        :param roundcoordinates: Whether to round coordinates to the nearest integer
        """

        # Meta
        self.matfilepath = matfilepath
        self.objectid = objectid
        self.roundcoordinates = roundcoordinates

        # Parse matfile to a position array
        self.posarray = ctrax2np(matpath=matfilepath)

        assert self.objectid < self.posarray.shape[1], "Object ID does not correspond to an object in the ctrax file."

    def getposition(self, T):
        if self.roundcoordinates:
            return np.round(self.posarray[T, self.objectid, :]).astype('int')
        else:
            return self.posarray[T, self.objectid, :]

    def __getitem__(self, item):
        if isinstance(item, slice):
            assert item.stop < self.posarray.shape[0]
            assert item.start >= 0
        elif isinstance(item, int):
            assert item < self.posarray.shape[0]
            assert item >= 0
        else:
            raise NotImplementedError("`item` must be a slice or an integer.")

        # Get position and return
        return self.getposition(item)


class VideoFrames(object):
    def __init__(self, path):

        assert os.path.isdir(path), "Path must be a directory."

        # Meta
        self.path = path

        # Parse directory
        self.filenames = None
        self.imshape = None
        self.maxT = len(self.filenames)

    def parsedir(self):
        # Filenames need to be sorted to get rid of the dictionary ordering
        self.filenames = sorted(glob.glob("{}/*.png".format(self.path)), key=lambda x: int(x.split('.')[0]))
        self.imshape = imread(self.filenames[0]).shape

    def fetchframes(self, stop=None, numsteps=None):
        """Fetch `numsteps` frames starting at `start` and concatenate along the 0-th axis."""

        frames = np.array([imread(self.filenames[framenum])
                           for framenum in range(stop - numsteps + 1, stop + 1)])[::-1, ...]
        return frames


# Default action function
def action_response_factory(stepsize=1):

    def action_response(env, action):

        # Determine whether to evolve system after action
        evolvesystem = not env.metatime and not env.isterminal()

        # Initialize a reward
        reward = None

        # Switch cases for action
        if action == 0:
            # Move up
            env.crosshair = env.crosshair + np.array([stepsize, 0])
            # Simulate
            if evolvesystem:
                env.episodeT += 1
            else:
                reward = env.getreward()

        elif action == 1:
            # Move down
            env.crosshair = env.crosshair + np.array([-stepsize, 0])
            # Simulate
            if evolvesystem:
                env.episodeT += 1
            else:
                reward = env.getreward()

        elif action == 2:
            # Move left
            env.crosshair = env.crosshair + np.array([0, -stepsize])
            # Simulate
            if evolvesystem:
                env.episodeT += 1
            else:
                reward = env.getreward()

        elif action == 3:
            # Move right
            env.crosshair = env.crosshair + np.array([0, stepsize])
            # Simulate
            if evolvesystem:
                env.episodeT += 1
            else:
                reward = env.getreward()

        elif action == 4:
            # Metatime: Next
            if not env.isterminal():
                env.episodeT += 1
            else:
                reward = env.getreward()

        else:
            raise RuntimeError("Invalid action.")

        nextstate = env.state

        return reward, nextstate

    return action_response
