import {Config} from '@remotion/cli/config';

// Matches the PIL pipeline's encode so the two sets of assets are one library:
// same codec, same pixel format, same CRF band. A reel that looks different in
// a feed because it was encoded differently is a real and avoidable tell.
Config.setVideoImageFormat('jpeg');
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
Config.setCrf(21);
Config.setOverwriteOutput(true);
