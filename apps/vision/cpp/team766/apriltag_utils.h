#ifndef APRILTAG_UTILS_H_
#define APRILTAG_UTILS_H_

extern "C" {
#include "apriltag.h"
#include "tag16h5.h"
#include "tag25h9.h"
#include "tag36h11.h"
#include "tagCircle21h7.h"
#include "tagCircle49h12.h"
#include "tagCustom48h12.h"
#include "tagStandard41h12.h"
#include "tagStandard52h13.h"
}

bool setup_tag_family(apriltag_family_t **tf, const char *famname);
void teardown_tag_family(apriltag_family_t **tf, const char *famname);

#endif
